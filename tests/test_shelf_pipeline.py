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
