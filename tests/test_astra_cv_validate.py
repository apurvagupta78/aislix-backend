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


def test_small_gap_is_approximate_and_uses_product_sum():
    payload = {
        "analysis_type": "shelf_cv",
        "products": [
            {"actual_facings": 30, "actual_visible_units": 30},
            {"actual_facings": 13, "actual_visible_units": 13},
        ],
        "summary": {"total_actual_facings": 44, "total_actual_visible_units": 43},
    }
    result = verify_astra_count_consistency(payload)
    assert result["count_verification_status"] == "APPROXIMATE"
    assert result["scan_complete"] is True
    assert result["total_actual_facings"]["status"] == "APPROXIMATE"
    assert result["total_actual_facings"]["gap"] == 1
    assert result["total_actual_facings"]["verified_value"] == 43
    assert result["total_actual_visible_units"]["status"] == "VERIFIED"


def test_tolerance_scales_with_shelf_size():
    payload = {
        "analysis_type": "shelf_cv",
        "products": [{"actual_facings": 200, "actual_visible_units": 200}],
        "summary": {"total_actual_facings": 206, "total_actual_visible_units": 209},
    }
    result = verify_astra_count_consistency(payload)
    assert result["total_actual_facings"]["status"] == "APPROXIMATE"
    assert result["total_actual_visible_units"]["status"] == "COUNT_MISMATCH"
    assert result["count_verification_status"] == "COUNT_MISMATCH"
    assert result["scan_complete"] is False


def test_large_gap_stays_mismatch():
    payload = {
        "analysis_type": "shelf_cv",
        "products": [{"actual_facings": 328, "actual_visible_units": 328}],
        "summary": {"total_actual_facings": 427, "total_actual_visible_units": 328},
    }
    result = verify_astra_count_consistency(payload)
    assert result["count_verification_status"] == "COUNT_MISMATCH"
    assert result["total_actual_facings"]["verified_value"] is None
