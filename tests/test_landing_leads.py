"""Tests for landing-page lead capture helpers."""

from __future__ import annotations

from app.landing_leads import (
    hash_ip,
    landing_metadata,
    landing_scan_response,
    load_sample_planogram,
    new_session_token,
    parse_utm,
    sanitize_landing_inventory,
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


def test_landing_metadata_sample_loads_planogram():
    from app.landing_leads import SAMPLE_DEFAULTS

    meta = landing_metadata(
        None,
        None,
        None,
        sample_id="lays-a1l",
        sample_defaults=SAMPLE_DEFAULTS["lays-a1l"],
    )
    assert meta["category"] == "Packaged Food & Snacks"
    assert meta["sub_category"] == "chips"
    assert len(meta.get("planogram_items") or []) >= 10


def test_load_sample_planogram_lays():
    items = load_sample_planogram("lays-a1l")
    assert len(items) >= 10
    brands = {i.get("brand") for i in items}
    assert "Lay's" in brands or "Lays" in brands


def test_shampoo_sample_defaults():
    from app.landing_leads import DEFAULT_SAMPLE_ID, SAMPLE_DEFAULTS

    assert DEFAULT_SAMPLE_ID == "toothpaste-a1l"
    meta = landing_metadata(
        None,
        None,
        None,
        sample_id="shampoo-a1z",
        sample_defaults=SAMPLE_DEFAULTS["shampoo-a1z"],
    )
    assert meta["category"] == "Personal Care"
    assert meta["sub_category"] == "shampoo"


def test_toothpaste_sample_defaults():
    from app.landing_leads import DEFAULT_SAMPLE_ID, SAMPLE_DEFAULTS, resolve_sample_image

    assert DEFAULT_SAMPLE_ID == "toothpaste-a1l"
    data, defaults = resolve_sample_image("toothpaste-a1l")
    assert len(data) > 1000
    assert defaults["sub_category"] == "toothpaste"
    assert defaults["category"] == "Personal Care"
    meta = landing_metadata(
        None,
        None,
        None,
        sample_id="toothpaste-a1l",
        sample_defaults=SAMPLE_DEFAULTS["toothpaste-a1l"],
    )
    assert meta["sub_category"] == "toothpaste"
    assert "planogram_items" not in meta
    assert "shelf_brand_guide" in meta
    assert "Doctor" in meta["shelf_brand_guide"]
    assert "Dabur" in meta["shelf_brand_guide"]


def test_public_base_url_from_headers_https():
    from app.landing_leads import public_base_url_from_headers

    url = public_base_url_from_headers(
        {
            "x-forwarded-proto": "https",
            "host": "aislix-backend-production.up.railway.app",
        }
    )
    assert url == "https://aislix-backend-production.up.railway.app"


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
        "inventory": [
            {"brand": "Lays", "quantity": 13, "compliance_status": "ok"},
            {"brand": "Unknown", "quantity": 6, "compliance_status": "needs_review", "counted_in_totals": False},
        ],
        "executive_summary": "Shelf looks good.",
        "annotated_image_base64": "img",
        "csv_base64": "Y3N2",
        "facings_debug": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4}],
        "planogram_compliance": {"compliance_percent": 100},
    }
    out = landing_scan_response(full, "session-token-1", sample_id="lays-a1l")
    assert out["landing_session_id"] == "session-token-1"
    assert out["scanned_at"]
    assert out["scan_mode"] == "sample_with_planogram"
    assert out["has_planogram"] is True
    assert out["sample_id"] == "lays-a1l"
    assert "planogram_compliance" not in out
    assert out["csv_base64"] == "Y3N2"
    assert out["inventory"][0]["status_label"] == "Detected"
    assert out["inventory"][1]["status_label"] == "Needs review"
    assert "compliance_status" not in out["inventory"][0]


def test_sanitize_landing_inventory():
    rows = sanitize_landing_inventory(
        [{"brand": "Lays", "compliance_status": "ok"}, {"brand": "X", "compliance_status": "needs_review"}]
    )
    assert rows[0]["status_label"] == "Detected"
    assert rows[1]["status_label"] == "Needs review"
