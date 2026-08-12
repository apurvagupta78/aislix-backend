"""Tests for inventory aggregation and label normalization."""

from __future__ import annotations

from app.inventory import aggregate_inventory, normalize_classified_labels


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
