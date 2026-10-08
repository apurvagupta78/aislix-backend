from app.reference_match import build_reference_match, is_reference_comparison
from app.location_analysis import build_location_analysis
from app.shelf_pipeline import run_shelf_cv_pipeline


def _row(product, brand, label, facings=2, units=4, price="85"):
    return {
        "product": product,
        "brand": brand,
        "variant": "1 kg",
        "category": "Grocery",
        "actual_facings": facings,
        "actual_visible_units": units,
        "location_label": label,
        "location_label_status": "READ",
        "rack_marker": "C",
        "visible_price": price,
        "price_source": "SHELF_TAG" if price else "NONE",
        "confidence": 0.9,
    }


def _line(product, brand, qty=6, price=None, location=None, line_no=1):
    return {
        "line_no": line_no,
        "raw_text": f"{brand} {product} 1kg x{qty}",
        "brand": brand,
        "product_name": product,
        "variant": "1 kg",
        "invoice_qty": qty,
        "quantity_unit": "pcs",
        "expected_price": price,
        "expected_location": location,
        "confidence": 0.95,
    }


def _payload(products):
    return {
        "analysis_type": "shelf_cv",
        "image_quality": "GOOD",
        "products": products,
        "location_labels": [],
        "summary": {
            "total_actual_facings": sum(p["actual_facings"] for p in products),
            "total_actual_visible_units": sum(p["actual_visible_units"] for p in products),
        },
    }


def test_is_reference_comparison_requires_basis_and_items():
    assert is_reference_comparison({"comparison_basis": "reference", "reference_items": [{"brand": "A"}]})
    assert not is_reference_comparison({"comparison_basis": "reference", "reference_items": []})
    assert not is_reference_comparison({"reference_items": [{"brand": "A"}]})


def test_all_lines_found_with_matching_price_and_bin_is_a_match():
    products = [_row("Pink Rock Salt", "Catch", "AMB-D0703"), _row("Mixed Fruit Jam", "Kissan", "AMB-D0302", price="160")]
    lines = [
        _line("Pink Rock Salt", "Catch", qty=4, price=85, location="AMB-D0703", line_no=1),
        _line("Mixed Fruit Jam", "Kissan", qty=2, price=160, location="AMB-D0302", line_no=2),
    ]
    out = build_reference_match(lines, products, build_location_analysis(products, {}), count_pending=False)

    assert out["verdict"] == "MATCHES"
    assert out["metrics"]["presence_percent"] == 100.0
    assert out["metrics"]["price_lines_matched"] == 2
    assert out["metrics"]["location_lines_correct"] == 2
    assert [line["qty_status"] for line in out["lines"]] == ["COVERED", "COVERED"]
    assert out["not_on_document"] == []


def test_price_mismatch_missing_line_and_extra_product():
    products = [
        _row("Pink Rock Salt", "Catch", "AMB-D0703", price="90"),
        _row("Basmati Rice", "India Gate", "AMB-D0704"),
    ]
    lines = [
        _line("Pink Rock Salt", "Catch", qty=10, price=85, line_no=1),
        _line("Mixed Fruit Jam", "Kissan", qty=2, price=160, line_no=2),
    ]
    out = build_reference_match(lines, products, build_location_analysis(products, {}), count_pending=False)

    salt, jam = out["lines"]
    assert salt["presence_status"] == "FOUND"
    assert salt["price_status"] == "MISMATCH"
    assert salt["price_difference"] == 5
    assert salt["qty_status"] == "BELOW_DOCUMENT"
    assert salt["location_status"] == "NO_EXPECTED"
    assert jam["presence_status"] == "MISSING"
    assert jam["qty_status"] == "NOT_ON_SHELF"
    assert out["metrics"]["presence_percent"] == 50.0
    assert out["verdict"] == "DOES_NOT_MATCH"
    assert [row["brand"] for row in out["not_on_document"]] == ["India Gate"]


def test_unconfirmed_line_is_unclear_only_when_its_brand_is_on_the_shelf():
    products = [
        {**_row("Unverifiable", "Kissan", "AMB-D0302"), "product_status": "UNVERIFIABLE", "brand_status": "IDENTIFIED"},
    ]
    lines = [_line("Mixed Fruit Jam", "Kissan", qty=2), _line("Tomato Ketchup", "Maggi", qty=2, line_no=2)]
    out = build_reference_match(lines, products, build_location_analysis(products, {}), count_pending=False)
    statuses = {line["brand"]: line["presence_status"] for line in out["lines"]}
    assert statuses["Maggi"] == "MISSING"
    assert statuses["Kissan"] in {"FOUND_VARIANT_UNVERIFIED", "UNCLEAR"}


def test_count_pending_hides_shelf_quantities_and_unchecked_percentages_are_none():
    products = [_row("Pink Rock Salt", "Catch", "", price=None)]
    lines = [_line("Pink Rock Salt", "Catch", qty=4)]
    out = build_reference_match(lines, products, build_location_analysis(products, {}), count_pending=True)

    line = out["lines"][0]
    assert line["shelf_units"] is None
    assert line["qty_status"] == "PENDING"
    assert out["metrics"]["shelf_units_on_document_lines"] is None
    assert out["metrics"]["price_match_percent"] is None
    assert out["metrics"]["location_match_percent"] is None
    assert out["verdict"] == "MATCHES"


def test_pipeline_persists_reference_match_block():
    payload = _payload([_row("Pink Rock Salt", "Catch", "AMB-D0703")])
    metadata = {
        "analysis_mode": "planogram_comparison",
        "planogram_items": [{"brand": "Catch", "product_name": "Pink Rock Salt", "variant": "1 kg", "expected_qty": 1}],
        "comparison_basis": "reference",
        "reference_items": [_line("Pink Rock Salt", "Catch", qty=4, price=85, location="AMB-D0703")],
        "reference_document": {"document_type": "invoice", "supplier": "Acme Traders"},
    }
    result = run_shelf_cv_pipeline(payload, metadata)

    assert result["reference_match"]["verdict"] == "MATCHES"
    assert result["reference_match"]["document"]["supplier"] == "Acme Traders"
    assert result["aislix_planogram_analysis"]["reference_match"]["metrics"]["lines_found"] == 1


def _stock_list_metadata(document, facings=1):
    return {
        "analysis_mode": "planogram_comparison",
        "planogram_items": [
            {"brand": "Catch", "product_name": "Pink Rock Salt", "variant": "1 kg", "expected_facings": facings},
            {"brand": "Kissan", "product_name": "Mixed Fruit Jam", "variant": "1 kg", "expected_facings": facings},
        ],
        "comparison_basis": "reference",
        "reference_items": [
            _line("Pink Rock Salt", "Catch", qty=4),
            _line("Mixed Fruit Jam", "Kissan", qty=2, line_no=2),
        ],
        "reference_document": document,
    }


def test_stock_list_without_facings_marks_facing_compliance_not_applicable():
    payload = _payload([_row("Pink Rock Salt", "Catch", "AMB-D0703", facings=8, units=8)])
    result = run_shelf_cv_pipeline(payload, _stock_list_metadata({"source": "csv", "extra_columns": []}))

    analysis = result["aislix_planogram_analysis"]
    assert result["calculated_metrics"]["overall_facing_compliance"]["status"] == "NOT_APPLICABLE"
    assert analysis["facing_targets"] is False
    assert all(row["facing_compliance"]["status"] == "NOT_APPLICABLE" for row in analysis["products"])
    summary = result["executive_summary"]
    assert "800" not in summary and "None" not in summary
    assert "Mode: Document comparison" in summary
    assert "Not applicable (document has no facing targets)" in summary
    assert "Mixed Fruit Jam · 1 kg | not found on shelf" in summary


def test_planogram_document_keeps_facing_compliance():
    payload = _payload([_row("Pink Rock Salt", "Catch", "AMB-D0703", facings=2, units=4)])
    result = run_shelf_cv_pipeline(payload, _stock_list_metadata({"document_type": "planogram"}, facings=2))
    assert result["calculated_metrics"]["overall_facing_compliance"]["status"] == "CALCULATED"
    assert "facing_targets" not in result["aislix_planogram_analysis"]


def test_planogram_scans_report_products_and_brands_identified():
    payload = _payload([_row("Pink Rock Salt", "Catch", "AMB-D0703"), _row("Basmati Rice", "India Gate", "AMB-D0704")])
    result = run_shelf_cv_pipeline(payload, _stock_list_metadata({"source": "csv"}))
    metrics = result["calculated_metrics"]
    assert metrics["products_identified"]["value"] == 2
    assert metrics["brands_identified"]["value"] == 2
    assert "Products identified: 2" in result["executive_summary"]


def test_pipeline_without_reference_has_no_block():
    payload = _payload([_row("Pink Rock Salt", "Catch", "AMB-D0703")])
    result = run_shelf_cv_pipeline(payload, {"analysis_mode": "shelf_only"})
    assert "reference_match" not in result


def test_promotions_compare_document_promo_column_with_shelf_offer():
    salt = _row("Pink Rock Salt", "Catch", "AMB-D0703")
    salt.update({"promotion_text": "Buy 1 Get 1 Free", "promotion_type": "MULTI_BUY", "promo_price": None})
    jam = _row("Mixed Fruit Jam", "Kissan", "AMB-D0302", price="160")
    jam.update({"promotion_text": None, "promotion_type": "NONE", "promo_price": None})
    rice = _row("Basmati Rice", "India Gate", "AMB-D0704")
    rice.update({"promotion_text": "20% OFF", "promotion_type": "PRICE_OFF", "promo_price": "199"})
    honey = _row("Pure Honey", "Dabur", "AMB-D0705")
    honey.update({"promotion_text": "Save Rs 10", "promotion_type": "PRICE_OFF", "promo_price": "140"})
    lines = [
        {**_line("Pink Rock Salt", "Catch", line_no=1), "extra_fields": {"Promo": "BOGO"}},
        {**_line("Mixed Fruit Jam", "Kissan", line_no=2), "expected_promo": "10% off"},
        _line("Basmati Rice", "India Gate", line_no=3),
        {**_line("Ghee", "Amul", line_no=4), "extra_fields": {"Offer": "Free spoon"}},
    ]
    products = [salt, jam, rice, honey]
    out = build_reference_match(lines, products, build_location_analysis(products, {}), count_pending=False)

    by_line = {line["line_no"]: line for line in out["lines"]}
    assert by_line[1]["expected_promo"] == "BOGO"
    assert by_line[1]["shelf_promotion"] == "Buy 1 Get 1 Free"
    assert by_line[1]["promo_status"] == "PROMO_SEEN"
    assert by_line[2]["promo_status"] == "PROMO_NOT_SEEN"
    assert by_line[3]["promo_status"] == "UNEXPECTED_PROMO"
    assert by_line[3]["shelf_promo_price"] == "199"
    assert by_line[4]["promo_status"] == "NOT_ON_SHELF"
    assert out["not_on_document"][0]["shelf_promotion"] == "Save Rs 10"
    assert out["metrics"]["promo_lines_expected"] == 3
    assert out["metrics"]["promo_lines_seen"] == 1
    assert out["metrics"]["promo_lines_not_seen"] == 1
    assert out["metrics"]["shelf_promotions_read"] == 3


def test_scans_without_promotion_reading_report_no_expected_promo():
    products = [_row("Pink Rock Salt", "Catch", "AMB-D0703")]
    out = build_reference_match(
        [_line("Pink Rock Salt", "Catch")], products, build_location_analysis(products, {}), count_pending=False
    )
    line = out["lines"][0]
    assert line["expected_promo"] is None
    assert line["shelf_promotion"] is None
    assert line["promo_status"] == "NO_EXPECTED"
    assert out["metrics"]["promo_lines_expected"] == 0
