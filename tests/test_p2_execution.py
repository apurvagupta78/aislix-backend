"""P2 execution intelligence — audit scope, multi-photo merge, price compliance."""

from app.audit_scope import (
    SCOPE_ADJACENT,
    SCOPE_AUDITED,
    annotate_audit_scope,
    apply_audit_scope_after_compliance,
    scoped_misplaced_count,
)
from app.metrics import compute_competitor_intel
from app.multi_photo_merge import merge_classified_photos
from app.price_compliance import compute_price_compliance, extract_price_inr


def test_frame_edge_category_mismatch_excluded_from_placement_count():
    classified = [
        {
            "brand": "Frau",
            "product_name": "Water",
            "x1": 5,
            "y1": 100,
            "x2": 40,
            "y2": 200,
            "subcategory_match": False,
        },
        {
            "brand": "Colgate",
            "product_name": "Max Fresh",
            "x1": 200,
            "y1": 100,
            "x2": 280,
            "y2": 200,
            "subcategory_match": True,
        },
    ]
    image_shape = (400, 400, 3)
    annotate_audit_scope(classified, image_shape=image_shape, scan_context={"sub_category": "toothpaste"})
    assert classified[0]["audit_scope_zone"] == SCOPE_ADJACENT
    assert scoped_misplaced_count(classified) == 0


def test_in_scope_mismatch_counts_as_placement_violation():
    classified = [
        {
            "brand": "Frau",
            "product_name": "Water",
            "x1": 150,
            "y1": 100,
            "x2": 220,
            "y2": 200,
            "subcategory_match": False,
        },
    ]
    annotate_audit_scope(classified, image_shape=(400, 400, 3), scan_context={"sub_category": "toothpaste"})
    assert scoped_misplaced_count(classified) == 1


def test_filter_inventory_marks_adjacent_only_rows_out_of_totals():
    classified = [
        {
            "brand": "frau",
            "product_name": "water",
            "x1": 5,
            "y1": 100,
            "x2": 40,
            "y2": 200,
            "subcategory_match": False,
        },
    ]
    inventory = [{"brand": "Frau", "product_name": "Water", "quantity": 2}]
    _, filtered, _, _ = apply_audit_scope_after_compliance(
        classified,
        inventory,
        image_shape=(400, 400, 3),
        scan_context={"sub_category": "toothpaste"},
    )
    assert filtered[0]["counted_in_totals"] is False


def test_merge_classified_photos_dedupes_same_sku():
    batch_a = [
        {"brand": "Colgate", "product_name": "Max Fresh", "confidence": 0.7, "x1": 10, "y1": 10, "x2": 50, "y2": 90},
    ]
    batch_b = [
        {"brand": "Colgate", "product_name": "Max Fresh", "confidence": 0.9, "x1": 12, "y1": 12, "x2": 52, "y2": 92},
        {"brand": "Oral-B", "product_name": "Pro", "confidence": 0.8, "x1": 100, "y1": 10, "x2": 140, "y2": 90},
    ]
    merged = merge_classified_photos([batch_a, batch_b])
    assert merged["photo_count"] == 2
    assert merged["merged_facings"] == 2
    brands = {(r["brand"], r["product_name"]) for r in merged["classified"]}
    assert ("Colgate", "Max Fresh") in brands
    assert ("Oral-B", "Pro") in brands


def test_price_compliance_matches_ocr_to_planogram_mrp():
    classified = [
        {"brand": "colgate", "product_name": "max fresh", "pack_text": "MRP Rs. 100"},
    ]
    planogram = [
        {"brand": "Colgate", "product_name": "Max Fresh", "mrp_inr": 100, "avg_daily_sales": 5},
    ]
    result = compute_price_compliance(classified, planogram)
    assert result["state"] == "available"
    assert result["compliance_percent"] == 100.0
    assert extract_price_inr("Price INR 249") == 249.0


def test_competitor_intel_ignores_unknown_brands():
    shares = [
        {"brand": "Colgate", "share": 60.0, "quantity": 6},
        {"brand": "Unknown", "share": 40.0, "quantity": 4},
    ]
    intel = compute_competitor_intel(
        shares,
        primary_brand="Colgate",
        competitor_brands=["Pepsodent", "Unknown"],
    )
    assert intel is not None
    competitor_names = [row["brand"] for row in intel["competitor_shares"] if row.get("is_competitor")]
    assert "Unknown" not in competitor_names
