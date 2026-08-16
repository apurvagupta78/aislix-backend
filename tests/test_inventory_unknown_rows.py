"""Unknown / excluded facings appear in inventory for review but not planogram totals."""

from __future__ import annotations

from app.inventory import aggregate_inventory, inventory_counted_rows, inventory_to_api_products


def test_unknown_excluded_facings_visible_in_inventory():
    classified = [
        {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "exclude_from_inventory": True,
            "exclusion_reason": "top_partial_facing",
        }
        for _ in range(6)
    ] + [
        {
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "sku": "lays_indias_magic_masala_potato_chips",
            "confidence": 0.9,
        }
        for _ in range(13)
    ]
    inventory = aggregate_inventory(classified)
    assert len(inventory) == 2
    unknown = next(r for r in inventory if r["brand"] == "Unknown")
    assert unknown["quantity"] == 6
    assert unknown["counted_in_totals"] is False
    assert unknown["compliance_status"] == "needs_review"
    assert sum(r["quantity"] for r in inventory_counted_rows(inventory)) == 13

    products = inventory_to_api_products(inventory)
    assert any(p["brand"] == "Unknown" and p["needs_review"] for p in products)
    assert all(p.get("counted_in_totals", True) for p in products if p["brand"] == "Lays")
