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


def test_merges_same_brand_cap_and_body():
    body = {
        "brand": "Pantene",
        "product_name": "Hair Fall Control Shampoo",
        "confidence": 0.96,
        "x1": 100,
        "y1": 40,
        "x2": 170,
        "y2": 210,
    }
    cap = {
        "brand": "Pantene",
        "product_name": "Hair Fall Control Shampoo",
        "confidence": 0.965,
        "x1": 108,
        "y1": 40,
        "x2": 162,
        "y2": 95,
    }
    result = filter_nested_facings([body, cap])
    assert len(result) == 1
    assert result[0]["brand"] == "Pantene"


def test_drops_unknown_cap_on_labeled_bottle():
    body = {
        "brand": "Himalaya",
        "product_name": "Anti Hair Fall Shampoo",
        "confidence": 0.94,
        "x1": 100,
        "y1": 50,
        "x2": 165,
        "y2": 220,
    }
    cap = {
        "brand": "Unknown",
        "product_name": "Unidentified SKU",
        "confidence": 0.35,
        "x1": 108,
        "y1": 50,
        "x2": 158,
        "y2": 98,
    }
    result = filter_nested_facings([body, cap])
    assert len(result) == 1
    assert result[0]["brand"] == "Himalaya"


def test_row_slot_dedup_keeps_one_per_bottle():
    a = {"brand": "Dove", "confidence": 0.9, "x1": 10, "y1": 10, "x2": 55, "y2": 130}
    b = {"brand": "Dove", "confidence": 0.88, "x1": 18, "y1": 12, "x2": 48, "y2": 125}
    c = {"brand": "Pantene", "confidence": 0.9, "x1": 200, "y1": 10, "x2": 250, "y2": 130}
    result = filter_nested_facings([a, b, c])
    assert len(result) == 2


def test_merges_different_brands_same_column_keeps_best():
    """Cap/body mislabels in one column should collapse to a single facing."""
    body = {
        "brand": "Pantene",
        "product_name": "Lively Clean",
        "confidence": 0.97,
        "x1": 100,
        "y1": 55,
        "x2": 165,
        "y2": 210,
    }
    cap = {
        "brand": "Tresemme",
        "product_name": "Keratin Smooth",
        "confidence": 0.90,
        "x1": 108,
        "y1": 50,
        "x2": 158,
        "y2": 95,
    }
    result = filter_nested_facings([body, cap])
    assert len(result) == 1


def test_drops_narrow_unknown_gap_fragment():
    narrow = {
        "brand": "Unknown",
        "confidence": 0.35,
        "x1": 175,
        "y1": 60,
        "x2": 195,
        "y2": 110,
    }
    bottle = {
        "brand": "Tresemme",
        "confidence": 0.99,
        "x1": 140,
        "y1": 40,
        "x2": 200,
        "y2": 210,
    }
    other = {
        "brand": "Loreal",
        "confidence": 0.95,
        "x1": 220,
        "y1": 40,
        "x2": 280,
        "y2": 210,
    }
    result = filter_nested_facings([narrow, bottle, other])
    assert len(result) == 2
    assert all(r["brand"] != "Unknown" for r in result)
