"""Tests for landing-page lead capture helpers."""

from __future__ import annotations

from app.landing_leads import (
    hash_ip,
    landing_metadata,
    landing_scan_response,
    new_session_token,
    parse_utm,
    slim_scan_result,
)


def test_new_session_token_is_hex():
    token = new_session_token()
    assert len(token) == 32
    int(token, 16)


def test_hash_ip_is_stable():
    assert hash_ip("203.0.113.1") == hash_ip("203.0.113.1")
    assert hash_ip("203.0.113.1") != hash_ip("203.0.113.2")


def test_parse_utm_from_form():
    utm = parse_utm(
        {
            "utm_source": "linkedin",
            "utm_medium": "cpc",
            "utm_campaign": "retail-intelligence",
            "utm_content": None,
        }
    )
    assert utm["utm_source"] == "linkedin"
    assert utm["utm_medium"] == "cpc"
    assert utm["utm_campaign"] == "retail-intelligence"
    assert utm["utm_content"] is None


def test_landing_metadata_enables_facings():
    meta = landing_metadata("Personal Care", "A-1-Z", "A-1-Z")
    assert meta["export_facings"] is True
    assert meta["category"] == "Personal Care"
    assert meta["location"] == "A-1-Z"


def test_slim_scan_result_strips_heavy_fields():
    full = {
        "scan_id": "abc123",
        "metrics": {"total_products": 10},
        "inventory": [{"brand": "Lays"}],
        "pdf_base64": "huge",
        "csv_base64": "huge",
        "annotated_image_base64": "also-huge",
    }
    slim = slim_scan_result(full)
    assert slim["scan_id"] == "abc123"
    assert "pdf_base64" not in slim
    assert "csv_base64" not in slim
    assert "annotated_image_base64" not in slim


def test_landing_scan_response_shape():
    full = {
        "scan_id": "abc123",
        "metrics": {"total_products": 31, "shelf_health_score": 86},
        "inventory": [{"brand": "Lays", "quantity": 13}],
        "executive_summary": "Shelf looks good.",
        "annotated_image_base64": "img",
        "facings_debug": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4}],
    }
    out = landing_scan_response(full, "session-token-1")
    assert out["landing_session_id"] == "session-token-1"
    assert out["scan_id"] == "abc123"
    assert out["status"] == "completed"
    assert out["metrics"]["total_products"] == 31
    assert len(out["inventory"]) == 1
    assert out["annotated_image_base64"] == "img"
    assert out["facings_debug"][0]["x1"] == 1
