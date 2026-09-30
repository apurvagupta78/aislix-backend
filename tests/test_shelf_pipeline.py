from app.shelf_pipeline import run_shelf_cv_pipeline


def test_shelf_only_pipeline_verified():
    payload = {
        "analysis_type": "shelf_cv",
        "analysis_mode": "no_planogram",
        "operating_model": "supermarket",
        "image_quality": {"status": "GOOD", "confidence": 0.9, "reason": "clear"},
        "products": [
            {
                "brand": "Lay's",
                "brand_status": "IDENTIFIED",
                "product_name": "Potato Chips",
                "product_status": "IDENTIFIED",
                "variant": "Magic Masala",
                "variant_status": "IDENTIFIED",
                "actual_facings": 5,
                "actual_visible_units": 5,
                "confidence": 0.92,
            }
        ],
        "summary": {
            "products_detected": 1,
            "brands_detected": 1,
            "total_actual_facings": 5,
            "total_actual_visible_units": 5,
        },
    }
    result = run_shelf_cv_pipeline(payload, {"analysis_mode": "shelf_only"})
    assert result is not None
    assert result["scan_complete"] is True
    assert result["aislix_shelf_analysis"]["calculated_metrics"]["total_actual_facings"]["value"] == 5
    assert "executive_summary" in result


def _two_product_payload(units_a: int, units_b: int, summary_units: int) -> dict:
    return {
        "analysis_type": "shelf_cv",
        "image_quality": "GOOD",
        "products": [
            {"product": "Coca-Cola soft drink", "brand": "Coca-Cola", "variant": "Original",
             "category": "Cola", "actual_facings": 5, "actual_visible_units": units_a, "confidence": 0.9},
            {"product": "Pepsi soft drink", "brand": "Pepsi", "variant": "Original",
             "category": "Cola", "actual_facings": 4, "actual_visible_units": units_b, "confidence": 0.9},
        ],
        "summary": {"total_actual_facings": 9, "total_actual_visible_units": summary_units},
    }


def test_visible_units_capped_to_facings_per_product():
    payload = _two_product_payload(9, 8, 17)
    result = run_shelf_cv_pipeline(payload, {"analysis_mode": "shelf_only"})
    products = result["astra_cv_analysis"]["products"]
    assert [p["actual_visible_units"] for p in products] == [5, 4]
    assert [p["astra_actual_visible_units"] for p in products] == [9, 8]
    units_check = result["astra_cv_validation"]["total_actual_visible_units"]
    assert units_check["product_sum"] == 9
    assert units_check["verified_value"] == 9
    assert units_check["rows_capped_to_facings"] == 2
    calc = result["aislix_shelf_analysis"]["calculated_metrics"]
    assert calc["total_actual_visible_units"]["value"] == 9
    assert calc["total_actual_visible_units"]["value"] <= calc["total_actual_facings"]["value"]


def test_visible_units_below_facings_untouched():
    payload = _two_product_payload(3, 4, 7)
    result = run_shelf_cv_pipeline(payload, {"analysis_mode": "shelf_only"})
    products = result["astra_cv_analysis"]["products"]
    assert [p["actual_visible_units"] for p in products] == [3, 4]
    assert all("astra_actual_visible_units" not in p for p in products)
    assert "rows_capped_to_facings" not in result["astra_cv_validation"]["total_actual_visible_units"]
