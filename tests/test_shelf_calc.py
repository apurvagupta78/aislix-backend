from app.shelf_calc import (
    build_planogram_row_metrics,
    calculate_facing_compliance,
    calculate_facing_compliance_aggregate,
    calculate_visible_shelf_coverage_days,
    calculate_visible_unit_shortfall,
    calculate_visible_unit_value_gap,
)


def test_single_sku_golden_metrics():
    row = build_planogram_row_metrics(
        {
            "expected_facings": 10,
            "actual_facings": 8,
            "min_facings": 8,
            "max_facings": 12,
            "expected_shelf_units": 20,
            "actual_visible_units": 14,
            "expected_mrp_inr": 20,
            "avg_daily_sales": 5,
        }
    )
    assert calculate_facing_compliance(8, 10).value == 80.0
    assert row["facing_variance"]["value"] == -2
    assert row["min_max_facing_status"] == "WITHIN_RANGE"
    assert row["shelf_unit_compliance"]["value"] == 70.0
    assert row["visible_unit_shortfall"]["value"] == 6
    assert row["potential_visible_unit_value_gap"]["value"] == 120.0
    assert calculate_visible_shelf_coverage_days(14, 5).value == 2.8


def test_two_sku_weighted_facing_compliance():
    rows = [
        {"actual_facings": 8, "expected_facings": 10},
        {"actual_facings": 4, "expected_facings": 5},
    ]
    assert calculate_facing_compliance_aggregate(rows).value == 80.0
