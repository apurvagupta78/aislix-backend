"""
Regression fixture from Colgate Palmolive / Max Fresh screenshot audit (Sep 2026).

Assumptions documented in docs/audit-findings.md — not production overwrite values.
"""

from app.metrics import (
    apply_brand_share_to_metrics,
    brand_share,
    build_brand_share_payload,
    compute_metrics,
    count_identified_brands,
    finalize_execution_score,
    is_unclassified_brand,
)


def _colgate_fixture_inventory() -> list[dict]:
    """116 facings per screenshot reconstruction; mouthwash + water are category mismatches."""
    rows = [
        ("Colgate", 42, "ok"),
        ("Oral-B", 24, "ok"),
        ("Doctor", 12, "ok"),
        ("Closeup", 8, "ok"),
        ("Odol", 6, "ok"),
        ("Sensodyne", 6, "ok"),
        ("Kolynos", 6, "ok"),
        ("Unknown", 6, "category_mismatch"),
        ("Frau", 6, "category_mismatch"),
    ]
    return [
        {
            "brand": brand,
            "product_name": brand,
            "quantity": qty,
            "compliance_status": status,
            "counted_in_totals": True,
        }
        for brand, qty, status in rows
    ]


def test_colgate_category_denominator_is_104_not_116():
    inventory = _colgate_fixture_inventory()
    payload = build_brand_share_payload(inventory, audit_sub_category="toothpaste")
    assert payload["brand_share_denominator"] == 104
    assert payload["brand_share_scope"] == "eligible_category"


def test_colgate_share_in_category_is_40_4_not_36_2():
    inventory = _colgate_fixture_inventory()
    payload = build_brand_share_payload(inventory, audit_sub_category="toothpaste")
    colgate = next(row for row in payload["brand_share"] if row["brand"] == "Colgate")
    assert colgate["share"] == 40.4
    all_image = build_brand_share_payload(inventory, audit_sub_category=None)
    colgate_all = next(row for row in all_image["brand_share"] if row["brand"] == "Colgate")
    assert colgate_all["share"] == 36.2


def test_unknown_is_not_an_identified_brand():
    inventory = _colgate_fixture_inventory()
    assert count_identified_brands(inventory) == 8
    payload = build_brand_share_payload(inventory, audit_sub_category="toothpaste")
    assert payload["identified_brand_count"] == 7
    assert is_unclassified_brand("Unknown")
    assert payload.get("unclassified_facings") == 0


def test_recognition_coverage_among_detections():
    def _facing(brand: str, product: str) -> dict:
        return {
            "brand": brand,
            "product_name": product,
            "x1": 0,
            "y1": 0,
            "x2": 10,
            "y2": 10,
        }

    classified = [_facing("Colgate", "x") for _ in range(110)]
    classified.extend(_facing("unknown", "y") for _ in range(6))
    metrics = compute_metrics(
        _colgate_fixture_inventory(),
        classified,
        (400, 400, 3),
        100,
    )
    assert metrics["recognition_coverage_percent"] == 94.8


def test_execution_score_withheld_when_coverage_insufficient():
    metrics = {
        "availability_percent": 0.0,
        "planogram_sku_match_percent": 0.0,
        "planogram_compliance_percent": 0.0,
        "planogram_summary": {"expected": 1},
        "facing_compliance_percent": None,
        "placement_compliance_percent": None,
        "total_facings": 116,
    }
    finalize_execution_score(metrics)
    assert metrics.get("shelf_execution_score") is None
    assert metrics["retail_execution_score"]["state"] == "not_configured"


def test_apply_brand_share_sets_primary_brand_percent():
    inventory = _colgate_fixture_inventory()
    payload = build_brand_share_payload(inventory, audit_sub_category="toothpaste")
    metrics: dict = {}
    apply_brand_share_to_metrics(metrics, payload, primary_brand="Colgate")
    assert metrics["brand_share_percent"] == 40.4
