"""Tests for Make.com scan provider adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.landing_leads import landing_scan_response
from app.make_scan import (
    MakeScanError,
    build_facings_from_make_products,
    build_make_json_payload,
    build_make_multipart,
    call_make_webhook,
    openai_bbox_facings_trusted,
    parse_make_response,
    relabel_facings_by_vertical_order,
    use_make_provider,
    _parse_product_bbox,
)
from app.scan_post_process import finalize_make_scan


@pytest.fixture
def tiny_image() -> np.ndarray:
    return np.zeros((120, 160, 3), dtype=np.uint8)


def test_use_make_provider_env(monkeypatch):
    monkeypatch.delenv("SCAN_PROVIDER", raising=False)
    assert use_make_provider() is False
    monkeypatch.setenv("SCAN_PROVIDER", "make")
    assert use_make_provider() is True
    monkeypatch.setenv("SCAN_PROVIDER", "local")
    assert use_make_provider() is False


def test_build_make_json_payload_includes_metadata(tiny_image):
    payload = build_make_json_payload("abc123", tiny_image, {"category": "Personal Care"})
    assert payload["scan_id"] == "abc123"
    assert payload["image_mime"] == "image/jpeg"
    assert payload["metadata"]["category"] == "Personal Care"
    assert isinstance(payload["image_base64"], str) and len(payload["image_base64"]) > 20


def test_build_make_multipart_uses_image_field(tiny_image):
    files, data = build_make_multipart("abc123", tiny_image, {"category": "Personal Care", "sub_category": "toothpaste", "shelf_label": "A-1-L"})
    assert "image" in files
    assert files["image"][2] == "image/jpeg"
    assert data["scan_id"] == "abc123"
    assert data["category"] == "Personal Care"
    assert data["sub_category"] == "toothpaste"
    assert "audit_instructions" in json.loads(data["metadata"])


def test_parse_make_response_partial_inventory():
    parsed = parse_make_response(
        {
            "executive_summary": "Shelf looks healthy.",
            "inventory": [
                {"brand": "Dove", "product_name": "Shampoo", "quantity": 3, "facings": 3, "confidence": 0.9}
            ],
        }
    )
    assert parsed["is_full"] is False
    assert len(parsed["inventory"]) == 1
    assert parsed["executive_summary"] == "Shelf looks healthy."


def test_parse_make_response_full_pass_through():
    parsed = parse_make_response(
        {
            "inventory": [{"brand": "Dove", "product_name": "Shampoo", "quantity": 1}],
            "metrics": {"total_products": 1, "total_facings": 1},
            "executive_summary": "Done.",
        }
    )
    assert parsed["is_full"] is True


def test_parse_make_response_shelf_sense_products():
    parsed = parse_make_response(
        {
            "products": [
                {
                    "brand": "Crax",
                    "product": "Rings",
                    "variant": "",
                    "qty": 4,
                    "confidence": 0.99,
                    "shelf_position": "Top Left Front",
                },
                {
                    "brand": "Kurkure",
                    "product": "Masala Munch",
                    "variant": "",
                    "qty": 5,
                    "confidence": 0.99,
                    "shelf_position": "Top Left Front",
                },
            ]
        }
    )
    assert parsed["is_full"] is False
    assert len(parsed["inventory"]) == 2
    assert parsed["inventory"][0]["product_name"] == "Rings"
    assert parsed["inventory"][0]["quantity"] == 4


def test_parse_make_response_json_string_body():
    raw = json.dumps(
        {
            "products": [
                {"brand": "Lays", "product": "Chips", "qty": 3, "confidence": 0.95, "variant": ""}
            ]
        }
    )
    parsed = parse_make_response(raw)
    assert parsed["inventory"][0]["brand"] == "Lays"
    assert parsed["inventory"][0]["quantity"] == 3


def test_build_facings_from_openai_bbox():
    rows = [
        {
            "brand": "Frau",
            "product": "Water",
            "variant": "",
            "qty": 3,
            "confidence": 0.92,
            "product_category": "water",
            "bbox_2d": [50, 700, 200, 950],
        }
    ]
    facings = build_facings_from_make_products(rows, (1000, 800, 3))
    assert len(facings) == 1
    assert facings[0]["brand"] == "Frau"
    assert facings[0]["x2"] > facings[0]["x1"]
    assert facings[0]["y2"] > facings[0]["y1"]


def test_rejects_ceiling_floating_bbox():
    """GPT often returns boxes in empty ceiling space — backend drops them."""
    rows = [
        {
            "brand": "Colgate",
            "product": "Toothpaste",
            "variant": "MaxFresh",
            "qty": 12,
            "confidence": 0.9,
            "bbox_2d": [50, 20, 900, 150],
        },
        {
            "brand": "Colgate",
            "product": "Toothpaste",
            "variant": "Visible White",
            "qty": 8,
            "confidence": 0.9,
            "bbox_2d": [80, 180, 420, 480],
        },
    ]
    facings = build_facings_from_make_products(rows, (1600, 900, 3))
    assert len(facings) == 1
    assert facings[0]["variant"] == "Visible White"


def test_rejects_giant_top_strip_bbox():
    rows = [
        {
            "brand": "Colgate",
            "product": "Toothpaste",
            "variant": "",
            "qty": 40,
            "confidence": 0.85,
            "bbox_2d": [10, 10, 990, 200],
        }
    ]
    facings = build_facings_from_make_products(rows, (1600, 900, 3))
    assert facings == []


def test_rejects_oversized_bbox():
    rows = [
        {
            "brand": "Lays",
            "product": "Potato Chips",
            "variant": "Magic Masala",
            "qty": 19,
            "confidence": 0.95,
            "bbox_2d": [20, 50, 980, 950],
        }
    ]
    facings = build_facings_from_make_products(rows, (1000, 800, 3))
    assert facings == []


def test_clamps_bbox_to_image_bounds():
    bbox = _parse_product_bbox({"bbox_2d": [720, 880, 1020, 1020]}, 800, 1000)
    assert bbox is not None
    x1, y1, x2, y2 = bbox
    assert x1 >= 0 and y1 >= 0
    assert x2 < 800 and y2 < 1000
    assert x2 > x1 and y2 > y1


def test_rejects_bbox_with_top_edge_in_ceiling_zone():
    bbox = _parse_product_bbox({"bbox_2d": [100, 30, 500, 180]}, 800, 1000)
    assert bbox is None


def test_openai_bbox_not_trusted_when_too_few_boxes_for_skus():
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 18},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 10},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 10},
    ]
    facings = build_facings_from_make_products(
        [
            {"brand": "Lays", "variant": "Magic Masala", "bbox_2d": [120, 200, 880, 550]},
            {"brand": "Lays", "variant": "Tomato tango", "bbox_2d": [120, 560, 880, 720]},
        ],
        (1000, 800, 3),
    )
    assert len(facings) == 2
    assert openai_bbox_facings_trusted(facings, inventory, (1000, 800, 3)) is False


def test_relabel_facings_by_vertical_order_fixes_swapped_labels():
    facings = [
        {"x1": 10, "y1": 200, "x2": 100, "y2": 300, "brand": "Lays", "product_name": "Chips", "variant": "Tomato tango"},
        {"x1": 10, "y1": 50, "x2": 100, "y2": 150, "brand": "Lays", "product_name": "Chips", "variant": "American cream and onion"},
        {"x1": 10, "y1": 350, "x2": 100, "y2": 450, "brand": "Lays", "product_name": "Chips", "variant": "Magic Masala"},
    ]
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 18},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 10},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 10},
    ]
    planogram = [
        {"brand": "Lays", "variant": "Magic Masala"},
        {"brand": "Lays", "variant": "Tomato tango"},
        {"brand": "Lays", "variant": "American cream and onion"},
    ]
    relabeled = relabel_facings_by_vertical_order(facings, inventory, planogram_items=planogram)
    assert relabeled[0]["variant"] == "Magic Masala"
    assert relabeled[1]["variant"] == "Tomato tango"
    assert relabeled[2]["variant"] == "American cream and onion"


def test_finalize_make_scan_uses_yolo_overlay_by_default(tiny_image, monkeypatch):
    monkeypatch.setenv("MAKE_YOLO_OVERLAY_ONLY", "true")
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "true")
    parsed = parse_make_response(
        {
            "products": [
                {"brand": "Lays", "product": "Potato Chips", "variant": "Magic Masala", "qty": 6, "confidence": 0.99}
            ],
            "executive_summary": "Chip rack.",
        }
    )
    fake_boxes = [{"x1": 10, "y1": 40, "x2": 50, "y2": 65}, {"x1": 60, "y1": 40, "x2": 100, "y2": 65}]

    with patch("app.make_annotate._detect_product_boxes", return_value=fake_boxes):
        result = finalize_make_scan(
            tiny_image,
            scan_id="yolo-overlay-test",
            metadata={"category": "Packaged Food & Snacks", "sub_category": "chips", "export_facings": True},
            parsed=parsed,
            processing_ms=900,
        )

    assert result["metrics"]["detection_mode"] == "make.com+yolo_overlay"
    assert result["annotated_image_base64"]


def test_finalize_make_scan_uses_openai_bbox_for_annotated_image(tiny_image, monkeypatch):
    monkeypatch.setenv("MAKE_YOLO_OVERLAY_ONLY", "false")
    monkeypatch.setenv("MAKE_USE_OPENAI_BBOX", "true")
    monkeypatch.setenv("MAKE_SKU_BAND_ANNOTATE", "false")
    monkeypatch.setenv("MAKE_PLANOGRAM_BAND_ANNOTATE", "false")
    parsed = parse_make_response(
        {
            "products": [
                {
                    "brand": "Colgate",
                    "product": "Toothpaste",
                    "qty": 4,
                    "confidence": 0.95,
                    "bbox_2d": [100, 100, 400, 300],
                }
            ],
            "executive_summary": "Toothpaste shelf.",
        }
    )
    result = finalize_make_scan(
        tiny_image,
        scan_id="bbox-test",
        metadata={"category": "Personal Care", "sub_category": "toothpaste", "export_facings": True},
        parsed=parsed,
        processing_ms=800,
    )
    assert result["annotated_image_base64"]
    assert result["metrics"]["detection_mode"] == "make.com+openai_bbox"


def test_parse_make_response_preserves_shelf_rows():
    parsed = parse_make_response(
        {
            "products": [
                {
                    "brand": "Lays",
                    "product": "Potato Chips",
                    "variant": "Magic Masala",
                    "qty": 10,
                    "confidence": 0.99,
                    "shelf_position": "Top Left Front",
                },
                {
                    "brand": "Lays",
                    "product": "Potato Chips",
                    "variant": "Magic Masala",
                    "qty": 10,
                    "confidence": 0.99,
                    "shelf_position": "Middle Left Front",
                },
            ]
        }
    )
    assert len(parsed["inventory"]) == 2
    assert parsed["inventory"][0]["shelf_position"] == "Top Left Front"
    assert parsed["inventory"][1]["shelf_position"] == "Middle Left Front"


def test_parse_make_response_unwraps_body_key():
    parsed = parse_make_response(
        {
            "body": {
                "inventory": [{"brand": "Lays", "product_name": "Chips", "quantity": 2}],
                "facings": [
                    {"x1": 1, "y1": 2, "x2": 10, "y2": 20, "brand": "Lays", "product_name": "Chips"}
                ],
                "executive_summary": "Snack shelf.",
            }
        }
    )
    assert parsed["is_full"] is False
    assert len(parsed["facings"]) == 1


def test_finalize_make_scan_partial_inventory(tiny_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    parsed = parse_make_response(
        {
            "inventory": [
                {"brand": "Dove", "product_name": "Daily Shine Shampoo", "quantity": 2, "confidence": 0.88}
            ],
            "executive_summary": "Two Dove facings detected.",
        }
    )
    result = finalize_make_scan(
        tiny_image,
        scan_id="make-test",
        metadata={"category": "Personal Care", "sub_category": "shampoo"},
        parsed=parsed,
        processing_ms=1200,
    )
    assert result["model_version"] == "make.com"
    assert result["scan_id"] == "make-test"
    assert result["inventory"][0]["brand"] == "Dove"
    assert result["metrics"]["total_products"] == 2
    assert result["executive_summary"] == "Two Dove facings detected."
    assert result["csv_base64"]
    assert result["pdf_base64"]


def test_finalize_make_scan_with_facings(tiny_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    parsed = parse_make_response(
        {
            "facings": [
                {
                    "x1": 10,
                    "y1": 10,
                    "x2": 50,
                    "y2": 80,
                    "brand": "Head & Shoulders",
                    "product_name": "Anti Dandruff Shampoo",
                    "confidence": 0.91,
                },
                {
                    "x1": 60,
                    "y1": 10,
                    "x2": 100,
                    "y2": 80,
                    "brand": "Head & Shoulders",
                    "product_name": "Anti Dandruff Shampoo",
                    "confidence": 0.89,
                },
            ],
            "executive_summary": "Two facings.",
        }
    )
    result = finalize_make_scan(
        tiny_image,
        scan_id="facing-test",
        metadata={"category": "Personal Care"},
        parsed=parsed,
        processing_ms=900,
    )
    assert result["metrics"]["total_facings"] == 2
    assert result["inventory"][0]["quantity"] == 2


def test_landing_scan_response_works_with_make_result(tiny_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    parsed = parse_make_response(
        {
            "inventory": [{"brand": "Dove", "product_name": "Shampoo", "quantity": 1, "confidence": 0.8}],
            "executive_summary": "Demo scan.",
        }
    )
    full = finalize_make_scan(
        tiny_image,
        scan_id="landing-make",
        metadata={"export_facings": True, "category": "Personal Care"},
        parsed=parsed,
        processing_ms=500,
    )
    landing = landing_scan_response(full, "session-token-abc")
    assert landing["status"] == "completed"
    assert landing["landing_session_id"] == "session-token-abc"
    assert landing["inventory"][0]["status_label"] == "Detected"
    assert landing["metrics"]["total_products"] == 1


@patch("app.make_scan.requests.post")
def test_call_make_webhook_success(mock_post, monkeypatch, tiny_image):
    monkeypatch.setenv("MAKE_SCAN_WEBHOOK_URL", "https://hook.make.com/test")
    monkeypatch.setenv("MAKE_UPLOAD_MODE", "json")
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "inventory": [{"brand": "Dove", "product_name": "Shampoo", "quantity": 1}],
            "executive_summary": "OK",
        },
    )
    parsed = call_make_webhook(scan_id="x", image=tiny_image, metadata={})
    assert parsed["inventory"][0]["brand"] == "Dove"
    mock_post.assert_called_once()


@patch("app.make_scan.requests.post")
def test_call_make_webhook_multipart(mock_post, monkeypatch, tiny_image):
    monkeypatch.setenv("MAKE_SCAN_WEBHOOK_URL", "https://hook.make.com/test")
    monkeypatch.setenv("MAKE_UPLOAD_MODE", "multipart")
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"products": [{"brand": "Lays", "product": "Chips", "qty": 3, "confidence": 0.9, "variant": ""}]},
    )
    parsed = call_make_webhook(scan_id="x", image=tiny_image, metadata={"category": "Snacks"})
    assert parsed["inventory"][0]["brand"] == "Lays"
    _, kwargs = mock_post.call_args
    assert "files" in kwargs
    assert "image" in kwargs["files"]


@patch("app.make_scan.requests.post")
def test_call_make_webhook_http_error(mock_post, monkeypatch, tiny_image):
    monkeypatch.setenv("MAKE_SCAN_WEBHOOK_URL", "https://hook.make.com/test")
    monkeypatch.setenv("MAKE_UPLOAD_MODE", "json")
    mock_post.return_value = MagicMock(status_code=500, text="fail", reason="Error")
    with pytest.raises(MakeScanError, match="HTTP 500"):
        call_make_webhook(scan_id="x", image=tiny_image, metadata={})


@patch("app.make_scan.run_make_scan_from_image")
def test_pipeline_dispatches_to_make_when_enabled(mock_make, monkeypatch, tiny_image):
    monkeypatch.setenv("SCAN_PROVIDER", "make")
    mock_make.return_value = {"scan_id": "from-make", "model_version": "make.com", "inventory": []}
    from app.pipeline import run_scan_from_image

    result = run_scan_from_image(tiny_image, scan_id="from-make")
    assert result["model_version"] == "make.com"
    mock_make.assert_called_once()


@patch("app.make_scan.run_make_scan_from_image")
def test_pipeline_falls_back_to_local_on_make_failure(mock_make, monkeypatch, tiny_image):
    monkeypatch.setenv("SCAN_PROVIDER", "make")
    monkeypatch.setenv("MAKE_FALLBACK_LOCAL", "true")
    mock_make.side_effect = MakeScanError("webhook down")

    with patch("app.pipeline._detect_boxes_for_scan", return_value=([], "single_row", {})):
        from app.pipeline import run_scan_from_image

        with pytest.raises(ValueError, match="No products detected"):
            run_scan_from_image(tiny_image, scan_id="fallback-test")

    mock_make.assert_called_once()
