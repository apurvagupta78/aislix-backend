"""Tests for nested facing filter."""

from __future__ import annotations

from app.facing_filter import filter_nested_facings


def test_drops_unknown_cap_inside_bottle():
    bottle = {
        "brand": "Sunsilk",
        "product_name": "Shampoo",
        "confidence": 0.95,
        "x1": 100,
        "y1": 50,
        "x2": 160,
        "y2": 200,
    }
    cap = {
        "brand": "Unknown",
        "product_name": "Unidentified SKU",
        "confidence": 0.35,
        "x1": 110,
        "y1": 50,
        "x2": 150,
        "y2": 90,
    }
    result = filter_nested_facings([bottle, cap])
    assert len(result) == 1
    assert result[0]["brand"] == "Sunsilk"


def test_keeps_separate_bottles():
    a = {"brand": "Dove", "confidence": 0.9, "x1": 10, "y1": 10, "x2": 50, "y2": 120}
    b = {"brand": "Pantene", "confidence": 0.9, "x1": 200, "y1": 10, "x2": 240, "y2": 120}
    assert len(filter_nested_facings([a, b])) == 2
