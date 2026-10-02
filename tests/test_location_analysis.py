from app.location_analysis import (
    build_location_analysis,
    labels_match,
    location_status,
    price_status,
)
from app.shelf_pipeline import run_shelf_cv_pipeline


def _row(product, brand, label, facings=2, units=2, rack="C", price="85", status="READ"):
    return {
        "product": product,
        "brand": brand,
        "variant": "1 kg",
        "category": "Salt",
        "actual_facings": facings,
        "actual_visible_units": units,
        "location_label": label,
        "location_label_status": status,
        "rack_marker": rack,
        "visible_price": price,
        "price_source": "SHELF_TAG" if price else "NONE",
        "confidence": 0.9,
    }


def _payload(products, labels=None):
    total_f = sum(p["actual_facings"] for p in products)
    total_u = sum(p["actual_visible_units"] for p in products)
    return {
        "analysis_type": "shelf_cv",
        "image_quality": "GOOD",
        "products": products,
        "location_labels": labels or [],
        "summary": {"total_actual_facings": total_f, "total_actual_visible_units": total_u},
    }


def test_location_rollup_empty_labels_racks_and_prices():
    products = [
        _row("Pink Rock Salt", "Catch", "AMB-D0703", rack="B"),
        _row("Basmati Rice", "India Gate", "amb - d0703", facings=6, units=6, rack="B"),
        _row("Honey", "Dabur", "AMB-D0302", price=None),
        _row("Jam", "Kissan", None, status="NOT_VISIBLE"),
    ]
    labels = [{"label": "AMB-D0713", "status": "READ", "rack_marker": "B", "section_empty": True}]

    out = build_location_analysis(products, {"location_labels": labels})

    by_label = {row["label"]: row for row in out["locations"]}
    assert by_label["AMB-D0703"]["products"] == 2
    assert by_label["AMB-D0703"]["facings"] == 8
    assert by_label["AMB-D0713"]["empty"] is True
    assert [row["label"] for row in out["empty_locations"]] == ["AMB-D0713"]
    assert out["metrics"] == {
        "location_labels_read": 3,
        "empty_locations": 1,
        "racks_detected": 2,
        "products_without_location": 1,
        "prices_read": 3,
    }


def test_older_payload_without_location_fields_reports_unavailable_not_zero():
    out = build_location_analysis([{"product": "X", "brand": "Y", "actual_facings": 1}], {})
    assert out["available"] is False
    assert out["metrics"]["location_labels_read"] is None
    assert out["metrics"]["prices_read"] is None


def test_partial_label_wildcard_match():
    assert labels_match("AMB-D03?2", "AMB-D0302")
    assert not labels_match("AMB-D03?2", "AMB-D0313")


def test_wrong_location_only_when_expected_label_is_in_photo():
    photo = ["AMB-D0302", "AMB-D0303"]
    assert location_status("AMB-D0303", "AMB-D0302", photo) == "WRONG_LOCATION"
    assert location_status("AMB-D0302", "AMB-D0302", photo) == "CORRECT"
    assert location_status("A-1-L", "AMB-D0302", photo) == "EXPECTED_NOT_IN_PHOTO"
    assert location_status("", "AMB-D0302", photo) == "NO_EXPECTED"
    assert location_status("AMB-D0303", None, photo) == "NOT_READABLE"


def test_price_status():
    assert price_status(85, "85") == "MATCH"
    assert price_status("110", "₹ 120.00") == "MISMATCH"
    assert price_status(110, None) == "NOT_READABLE"
    assert price_status(None, "120") == "NO_EXPECTED"


def test_pipeline_shelf_only_exposes_location_analysis():
    payload = _payload(
        [_row("Pink Rock Salt", "Catch", "AMB-D0703"), _row("Pink Rock Salt", "Catch", "AMB-D0704")],
    )
    result = run_shelf_cv_pipeline(payload, {"analysis_mode": "shelf_only"})
    assert result["location_analysis"]["metrics"]["location_labels_read"] == 2
    assert result["aislix_shelf_analysis"]["location_analysis"]["available"] is True
    calc = result["aislix_shelf_analysis"]["calculated_metrics"]
    assert calc["variants_identified"]["value"] == 1


def test_pipeline_planogram_location_and_price_status():
    payload = _payload(
        [
            _row("Pink Rock Salt", "Catch", "AMB-D0703", price="90"),
            _row("Mixed Fruit Jam", "Kissan", "AMB-D0302", price="160"),
        ],
        labels=[{"label": "AMB-D0303", "status": "READ", "rack_marker": "C", "section_empty": True}],
    )
    metadata = {
        "analysis_mode": "planogram_comparison",
        "planogram_items": [
            {"brand": "Catch", "product_name": "Pink Rock Salt", "variant": "1 kg",
             "expected_facings": 2, "location": "AMB-D0703", "mrp_inr": 85},
            {"brand": "Kissan", "product_name": "Mixed Fruit Jam", "variant": "1 kg",
             "expected_facings": 2, "location": "AMB-D0303", "mrp_inr": 160},
        ],
    }
    result = run_shelf_cv_pipeline(payload, metadata)
    rows = {r["brand"]: r for r in result["aislix_planogram_analysis"]["products"]}
    assert rows["Catch"]["location_status"] == "CORRECT"
    assert rows["Catch"]["price_status"] == "MISMATCH"
    assert rows["Catch"]["price_difference"] == 5
    assert rows["Kissan"]["location_status"] == "WRONG_LOCATION"
    assert rows["Kissan"]["price_status"] == "MATCH"


def test_planogram_folds_same_product_from_other_bins_when_no_expected_location():
    payload = _payload(
        [
            _row("Pink Rock Salt", "Catch", "AMB-D0703", facings=2, units=2),
            _row("Pink Rock Salt", "Catch", "AMB-D0704", facings=3, units=3),
        ],
    )
    metadata = {
        "analysis_mode": "planogram_comparison",
        "planogram_items": [
            {"brand": "Catch", "product_name": "Pink Rock Salt", "variant": "1 kg", "expected_facings": 5},
        ],
    }
    result = run_shelf_cv_pipeline(payload, metadata)
    row = result["aislix_planogram_analysis"]["products"][0]
    assert row["actual_facings"] == 5
    assert row["additional_location_labels"] == ["AMB-D0704"]
