"""Regression tests for KPI integrity — Max Fresh case and financial semantics."""

from app.metrics import compute_financial_impact, compute_shelf_execution_score_from_components


def test_max_fresh_oos_revenue_at_risk_uses_velocity_not_expected_qty():
    """Price ₹100 × 5 units/day = ₹500/day — not ₹100 × 15 expected facings."""
    planogram_items = [
        {
            "brand": "Colgate",
            "product_name": "Max Fresh",
            "variant": "340ml",
            "expected_qty": 15,
            "mrp_inr": 100,
            "avg_daily_sales": 5,
            "shelf_position": "1",
        }
    ]
    planogram_compliance = {
        "lines": [
            {
                "issue_type": "missing",
                "expected_brand": "Colgate",
                "expected_product": "Max Fresh",
                "expected_qty": 15,
                "actual_qty": 0,
            }
        ]
    }

    impact = compute_financial_impact(
        inventory=[],
        metrics={"low_stock_threshold": 2},
        planogram_items=planogram_items,
        planogram_compliance=planogram_compliance,
    )

    assert impact["level"] == 2
    assert impact["estimated_daily_lost_sales_inr"] == 500
    assert impact["estimated_monthly_lost_sales_inr"] == 15000
    assert "run-rate" in impact["methodology"].lower()
    assert impact.get("assumption")


def test_execution_score_withheld_when_coverage_insufficient():
    """Single low-weight KPI must not produce a misleading headline score."""
    components = [
        {"key": "share", "label": "Share", "score": 95.0, "state": "available", "weight": 10},
    ]
    assert compute_shelf_execution_score_from_components(components) is None


def test_execution_score_renormalizes_available_kpis():
    components = [
        {"key": "availability", "label": "Availability", "score": 0.0, "state": "available", "weight": 25},
        {"key": "planogram", "label": "Planogram SKU presence", "score": 0.0, "state": "available", "weight": 20},
        {"key": "share", "label": "Share of facings", "score": 36.2, "state": "available", "weight": 10},
    ]
    score = compute_shelf_execution_score_from_components(components)
    assert score is not None
    assert score < 20
