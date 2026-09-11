"""P0 retail execution trust tests — evidence, image quality, ledger dedup."""

from app.retail_execution import _dedupe_opportunity_ledger, build_image_quality
from app.stockout_evidence import apply_stockout_evidence_to_metrics


def test_image_quality_not_perfect_without_ocr_assessment():
    payload = build_image_quality(
        {
            "total_facings": 116,
            "recognition_coverage_percent": 95.0,
            "ocr_empty_facings": 0,
            "ocr_low_confidence_facings": 0,
        },
        None,
    )
    score = payload["audit_image_quality_score"]["value"]
    assert score < 100
    assert payload.get("ocr_quality_assessed") is False
    assert payload["overall_state"] == "partial"


def test_apply_stockout_evidence_from_planogram_missing():
    metrics: dict = {"confirmed_oos_count": 5, "suspected_shelf_gap_count": 5}
    apply_stockout_evidence_to_metrics(
        metrics,
        planogram_compliance={
            "lines": [
                {
                    "issue_type": "missing",
                    "expected_brand": "Colgate",
                    "expected_product": "Max Fresh",
                    "actual_qty": 0,
                }
            ]
        },
        planogram_items=[
            {"brand": "Colgate", "product_name": "Max Fresh", "sku": ""},
        ],
    )
    assert metrics["verified_shelf_absence_count"] == 1
    assert metrics["confirmed_oos_count"] == 1


def test_opportunity_ledger_dedupes_same_sku_root_cause():
    ledger = _dedupe_opportunity_ledger(
        [
            {
                "brand": "Colgate",
                "sku": "Max Fresh",
                "issue": "missing",
                "commercial_impact_score": 50,
            },
            {
                "brand": "Colgate",
                "sku": "Max Fresh",
                "issue": "oos",
                "commercial_impact_score": 80,
            },
        ]
    )
    assert len(ledger) == 1
    assert ledger[0]["commercial_impact_score"] == 80
