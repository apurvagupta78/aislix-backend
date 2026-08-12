"""Tests for nested facing filter."""

from __future__ import annotations

from app.facing_filter import cluster_boxes_x_slots, filter_nested_facings, merge_boxes_by_column


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


def test_merge_stacked_half_bottle_unknowns():
    """Two stacked half-bottle Unknown boxes collapse to one facing."""
    upper = {
        "brand": "Unknown",
        "confidence": 0.35,
        "x1": 100,
        "y1": 50,
        "x2": 160,
        "y2": 120,
    }
    lower = {
        "brand": "Unknown",
        "confidence": 0.35,
        "x1": 102,
        "y1": 118,
        "x2": 158,
        "y2": 200,
    }
    result = filter_nested_facings([upper, lower])
    assert len(result) == 1


def test_merge_boxes_by_column_stacks_halves():
    import numpy as np

    upper = np.array([100.0, 50.0, 160.0, 120.0])
    lower = np.array([102.0, 118.0, 158.0, 200.0])
    left = np.array([10.0, 50.0, 70.0, 200.0])
    merged = merge_boxes_by_column([upper, lower, left])
    assert len(merged) == 2


def test_merge_boxes_by_column_keeps_separate_bottles():
    import numpy as np

    a = np.array([10.0, 50.0, 70.0, 200.0])
    b = np.array([200.0, 50.0, 260.0, 200.0])
    assert len(merge_boxes_by_column([a, b])) == 2


def test_single_row_dedup_one_per_column():
    facings = [
        {"brand": "Sunsilk", "confidence": 0.98, "x1": 100, "y1": 50, "x2": 160, "y2": 200},
        {"brand": "Unknown", "confidence": 0.35, "x1": 105, "y1": 50, "x2": 155, "y2": 95},
        {"brand": "Pantene", "confidence": 0.96, "x1": 200, "y1": 50, "x2": 260, "y2": 200},
        {"brand": "Unknown", "confidence": 0.35, "x1": 205, "y1": 50, "x2": 255, "y2": 95},
    ]
    result = filter_nested_facings(facings, layout="single_bin")
    assert len(result) == 2
    brands = {r["brand"] for r in result}
    assert brands == {"Sunsilk", "Pantene"}


def test_cluster_boxes_x_slots_merges_cap_and_body():
    import numpy as np

    cap = np.array([100.0, 50.0, 150.0, 95.0])
    body = np.array([102.0, 90.0, 148.0, 210.0])
    other = np.array([220.0, 50.0, 270.0, 210.0])
    merged = cluster_boxes_x_slots([cap, body, other])
    assert len(merged) == 2


def test_keeps_unknown_when_neighbor_label_low_confidence():
    """Snack bags mislabeled at low confidence should not suppress Unknown facings."""
    unknown_bag = {
        "brand": "Unknown",
        "product_name": "Unidentified SKU",
        "confidence": 0.55,
        "x1": 100,
        "y1": 50,
        "x2": 170,
        "y2": 210,
    }
    wrong_label = {
        "brand": "Haldiram",
        "product_name": "Snacks",
        "confidence": 0.68,
        "x1": 102,
        "y1": 55,
        "x2": 168,
        "y2": 205,
    }
    result = filter_nested_facings([unknown_bag, wrong_label])
    assert len(result) == 1
    assert result[0]["brand"] == "Unknown"


def test_drops_unknown_cap_when_neighbor_high_confidence():
    body = {
        "brand": "Lays",
        "product_name": "Potato Chips",
        "confidence": 0.92,
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
    assert result[0]["brand"] == "Lays"


def test_merge_boxes_by_column_does_not_merge_across_shelf_rows():
    """Same x-column on row 1 and row 2 must stay separate (multi-row shelf)."""
    import numpy as np

    row1 = np.array([100.0, 80.0, 160.0, 200.0])
    row2 = np.array([102.0, 280.0, 158.0, 400.0])
    row3 = np.array([104.0, 480.0, 156.0, 600.0])
    merged = merge_boxes_by_column([row1, row2, row3])
    assert len(merged) == 3
    for box in merged:
        assert box[3] - box[1] < 250  # no full-shelf-height strip
