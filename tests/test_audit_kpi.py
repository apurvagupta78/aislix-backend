"""Unit tests for deterministic audit KPI calculators (spec numerical + edge cases)."""

from __future__ import annotations

import pytest

from app.audit_kpi_calculators import (
    compute_assortment_compliance,
    compute_facing_count,
    compute_location_accuracy,
    compute_msl_compliance,
    compute_osa,
    compute_planogram_compliance,
    compute_price_compliance,
    compute_promotional_compliance,
    compute_share_of_shelf,
)
from app.audit_kpi_engine import compute_role_audit_dashboard
from app.role_kpi_config import ROLE_PROFILES, get_role_profile


class TestSpecNumericalFormulas:
    def test_osa_90_with_coverage_80(self):
        result = compute_osa(listed_available=18, listed_assessed=20, listed_eligible=25)
        assert result.value == 90.0
        assert result.coverage_percent == 80.0
        assert result.excluded_count == 5
        assert result.status == "partial"

    def test_planogram_compliance_84(self):
        result = compute_planogram_compliance(positions_passing=42, positions_assessed=50, positions_eligible=50)
        assert result.value == 84.0
        assert result.status == "complete"

    def test_assortment_compliance_90(self):
        result = compute_assortment_compliance(present_required=27, assessed_required=30, eligible_required=30)
        assert result.value == 90.0

    def test_price_compliance_95(self):
        result = compute_price_compliance(labels_passing=19, labels_assessed=20, labels_eligible=20)
        assert result.value == 95.0

    def test_promotional_compliance_75(self):
        result = compute_promotional_compliance(
            promotions_passing=3, promotions_assessed=4, promotions_eligible=4, active_promotions=4
        )
        assert result.value == 75.0

    def test_location_accuracy_92(self):
        result = compute_location_accuracy(locations_correct=46, locations_assessed=50, locations_eligible=50)
        assert result.value == 92.0

    def test_facing_count_sum(self):
        result = compute_facing_count(actual_facings=4 + 3 + 5, planned_facings=15)
        assert result.value == 12
        assert result.unit == "count"

    def test_share_of_shelf_30(self):
        result = compute_share_of_shelf(brand_linear_cm=120, total_linear_cm=400, calibrated=True)
        assert result.value == 30.0

    def test_msl_compliance_90(self):
        result = compute_msl_compliance(present_msl=9, assessed_msl=10, eligible_msl=10)
        assert result.value == 90.0


class TestEdgeCases:
    def test_zero_eligible_units_not_applicable(self):
        result = compute_osa(listed_available=0, listed_assessed=0, listed_eligible=0)
        assert result.status == "not_applicable"
        assert result.value is None

    def test_no_assessable_evidence(self):
        result = compute_osa(listed_available=0, listed_assessed=0, listed_eligible=10)
        assert result.status == "not_assessable"
        assert result.value is None

    def test_promotions_not_applicable_when_none_active(self):
        result = compute_promotional_compliance(
            promotions_passing=0, promotions_assessed=0, promotions_eligible=0, active_promotions=0
        )
        assert result.status == "not_applicable"
        assert result.value is None

    def test_sos_not_assessable_without_calibration(self):
        result = compute_share_of_shelf(brand_linear_cm=0, total_linear_cm=0, calibrated=False)
        assert result.status == "not_assessable"
        assert result.value is None

    def test_facing_count_partial_coverage(self):
        result = compute_facing_count(
            actual_facings=8, planned_facings=12, positions_assessed=3, positions_eligible=5, partial_coverage=True
        )
        assert result.status == "partial"
        assert "partial" in " ".join(result.warnings).lower()


class TestRoleProfiles:
    @pytest.mark.parametrize("role_id", list(ROLE_PROFILES.keys()))
    def test_exactly_five_primary_kpis_per_role(self, role_id: str):
        profile = get_role_profile(role_id)
        assert len(profile["primary_kpis"]) == 5

    def test_supermarket_kpi_ids(self):
        ids = [k["kpi_id"] for k in get_role_profile("supermarket")["primary_kpis"]]
        assert ids == ["osa", "planogram_compliance", "assortment_compliance", "price_compliance", "promotional_compliance"]


class TestRoleDashboardIntegration:
    def test_supermarket_dashboard_with_planogram(self):
        planogram_items = [
            {
                "id": "1",
                "brand": "Colgate",
                "product_name": "MaxFresh",
                "match_key": "colgate|maxfresh",
                "expected_facings": 4,
                "mrp_inr": 99,
                "shelf_position": "S1-L1",
            },
            {
                "id": "2",
                "brand": "Pepsodent",
                "product_name": "Germicheck",
                "match_key": "pepsodent|germicheck",
                "expected_facings": 3,
                "mrp_inr": 85,
                "shelf_position": "S1-L2",
            },
        ]
        inventory = [
            {"brand": "Colgate", "product_name": "MaxFresh", "match_key": "colgate|maxfresh", "quantity": 4, "facings": 4},
            {"brand": "Pepsodent", "product_name": "Germicheck", "match_key": "pepsodent|germicheck", "quantity": 0, "facings": 0},
        ]
        compliance = {
            "lines": [
                {"planogram_item_id": "1", "issue_type": "correct", "actual_qty": 4},
                {"planogram_item_id": "2", "issue_type": "missing", "actual_qty": 0},
            ]
        }
        dashboard = compute_role_audit_dashboard(
            customer_type="supermarket",
            planogram_items=planogram_items,
            planogram_compliance=compliance,
            inventory=inventory,
            classified=[],
            price_compliance={"state": "available", "lines": []},
            planogram_package={"assortment_skus": planogram_items},
        )
        assert dashboard["kpi_count"] == 5
        osa = next(k for k in dashboard["primary_kpis"] if k["kpi_id"] == "osa")
        assert osa["numerator"] == 1
        assert osa["denominator"] == 2
        assert osa["value"] == 50.0
