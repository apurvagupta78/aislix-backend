"""Tests for inventory aggregation and label normalization."""

from __future__ import annotations

from app.inventory import aggregate_inventory, merge_inventory_rows, normalize_classified_labels


def test_merges_crax_rings_casing_variants():
    classified = [
        {"brand": "Crax", "product_name": "Rings", "confidence": 0.9},
        {"brand": "CRAX", "product_name": "RINGS", "confidence": 0.85},
    ]
    inventory = aggregate_inventory(classified)
    assert len(inventory) == 1
    assert inventory[0]["brand"] == "Crax"
    assert inventory[0]["product_name"] == "Rings"
    assert inventory[0]["quantity"] == 2


def test_normalize_classified_labels_canonical_display():
    rows = normalize_classified_labels(
        [
            {"brand": "lay's", "product_name": "POTATO CHIPS", "confidence": 0.8},
            {"brand": "LAYS", "product_name": "potato chips", "confidence": 0.7},
        ]
    )
    assert rows[0]["brand"] == "Lays"
    assert rows[0]["product_name"] == "Potato Chips"
    assert rows[1]["brand"] == "Lays"
    assert rows[1]["product_name"] == "Potato Chips"


def test_merges_tomato_tango_name_variants():
    classified = [
        {"brand": "Lays", "product_name": "Tomato Tango", "confidence": 0.84},
        {"brand": "Lays", "product_name": "Tomato Tango Potato Chips", "confidence": 0.84},
    ]
    inventory = aggregate_inventory(classified)
    assert len(inventory) == 1
    assert inventory[0]["quantity"] == 2
    assert "Tomato Tango" in inventory[0]["product_name"]


def test_merges_same_sku_with_different_product_text():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Daily Shine Shampoo",
            "sku": "dove_daily_shine_shampoo_180ml",
            "confidence": 0.98,
        },
        {
            "brand": "Dove",
            "product_name": "Daily Shine Shampoo 180 Ml Bottle",
            "sku": "dove_daily_shine_shampoo_180ml",
            "confidence": 0.96,
        },
    ]
    inventory = aggregate_inventory(classified)
    assert len(inventory) == 1
    assert inventory[0]["quantity"] == 2


def test_merges_variant_placeholders_into_one_row():
    classified = [
        {"brand": "Tata", "product_name": "Tea Agni", "variant": "Unknown", "confidence": 0.86},
        {"brand": "Tata", "product_name": "Tea Agni", "variant": "Unidentified SKU", "confidence": 0.82},
        {"brand": "Tata", "product_name": "Tea Agni", "variant": "", "confidence": 0.88},
    ]
    inventory = aggregate_inventory(classified)
    assert len(inventory) == 1
    assert inventory[0]["quantity"] == 3
    assert inventory[0]["product_name"] == "Tea Agni"


def test_merge_inventory_rows_sums_duplicate_skus():
    rows = [
        {
            "brand": "Colgate",
            "product_name": "Toothpaste",
            "variant": "Triple Acción",
            "quantity": 21,
            "confidence": 0.99,
        },
        {
            "brand": "Colgate",
            "product_name": "Toothpaste",
            "variant": "Triple Acción",
            "quantity": 16,
            "confidence": 0.95,
        },
        {
            "brand": "Odol",
            "product_name": "Toothpaste",
            "variant": "Original",
            "quantity": 8,
            "confidence": 0.99,
        },
    ]
    merged = merge_inventory_rows(rows)
    assert len(merged) == 2
    colgate = next(r for r in merged if r["brand"] == "Colgate")
    assert colgate["quantity"] == 37
    assert colgate["facings"] == 37
    assert colgate["confidence"] == 0.99
