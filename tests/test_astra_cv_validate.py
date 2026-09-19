from app.astra_cv_validate import verify_astra_count_consistency


def test_count_verified_when_sums_match():
    payload = {
        "analysis_type": "shelf_cv",
        "products": [
            {"actual_facings": 8, "actual_visible_units": 14},
            {"actual_facings": 4, "actual_visible_units": 6},
        ],
        "summary": {"total_actual_facings": 12, "total_actual_visible_units": 20},
    }
    result = verify_astra_count_consistency(payload)
    assert result["count_verification_status"] == "VERIFIED"
    assert result["scan_complete"] is True
    assert result["total_actual_facings"]["verified_value"] == 12


def test_count_mismatch_blocks_verified_totals():
    payload = {
        "analysis_type": "shelf_cv",
        "products": [{"actual_facings": 8, "actual_visible_units": 14}],
        "summary": {"total_actual_facings": 25, "total_actual_visible_units": 14},
    }
    result = verify_astra_count_consistency(payload)
    assert result["count_verification_status"] == "COUNT_MISMATCH"
    assert result["scan_complete"] is False
    assert result["total_actual_facings"]["verified_value"] is None
    assert result["total_actual_facings"]["product_sum"] == 8
    assert result["total_actual_facings"]["astra_summary"] == 25
