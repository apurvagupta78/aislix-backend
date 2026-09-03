"""Tests for Make.com local YOLO annotation label assignment."""

from __future__ import annotations

from unittest.mock import patch

from app.make_annotate import (
    _assign_inventory_to_boxes,
    _filter_product_zone_boxes,
    _proportional_row_counts,
    build_planogram_sku_band_facings,
)


def test_proportional_row_counts_lays_rack():
    counts = _proportional_row_counts(6, [19, 6, 12])
    assert counts == [3, 1, 2]


def test_filter_product_zone_boxes_drops_ceiling():
    img_h = 1000
    boxes = [
        {"x1": 10, "y1": 20, "x2": 100, "y2": 80},
        {"x1": 10, "y1": 300, "x2": 100, "y2": 380},
    ]
    kept = _filter_product_zone_boxes(boxes, img_h)
    assert len(kept) == 1
    assert kept[0]["y1"] == 300


def test_assign_inventory_groups_rows_by_planogram_qty():
    boxes = []
    for row in range(6):
        y1 = 150 + row * 120
        for col in range(4):
            boxes.append(
                {
                    "x1": 50 + col * 80,
                    "y1": y1,
                    "x2": 110 + col * 80,
                    "y2": y1 + 80,
                }
            )
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 17},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 15},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 10},
    ]
    planogram = [
        {"brand": "Lays", "variant": "Magic Masala", "expected_qty": 19},
        {"brand": "Lays", "variant": "Tomato tango", "expected_qty": 6},
        {"brand": "Lays", "variant": "American cream and onion", "expected_qty": 12},
    ]
    labeled = _assign_inventory_to_boxes(boxes, inventory, planogram_items=planogram, img_h=1000)
    magic = [b for b in labeled if b["variant"] == "Magic Masala"]
    tomato = [b for b in labeled if b["variant"] == "Tomato tango"]
    cream = [b for b in labeled if b["variant"] == "American cream and onion"]
    assert len(magic) == 12
    assert len(tomato) == 4
    assert len(cream) == 8
    assert all((b["y1"] + b["y2"]) / 2 < 510 for b in magic)
    assert all(510 <= (b["y1"] + b["y2"]) / 2 < 630 for b in tomato)
    assert all((b["y1"] + b["y2"]) / 2 >= 630 for b in cream)


def test_build_planogram_sku_band_facings_one_box_per_sku_with_qty():
    import numpy as np

    image = np.zeros((1000, 800, 3), dtype=np.uint8)
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 18},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 12},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 12},
    ]
    planogram = [
        {"brand": "Lays", "variant": "Magic Masala", "expected_qty": 19},
        {"brand": "Lays", "variant": "Tomato tango", "expected_qty": 6},
        {"brand": "Lays", "variant": "American cream and onion", "expected_qty": 12},
    ]
    fake_boxes = [
        (50, 180, 120, 260),
        (50, 300, 120, 380),
        (50, 420, 120, 500),
        (50, 540, 120, 620),
        (50, 660, 120, 740),
        (50, 780, 120, 860),
    ]

    with patch("app.make_annotate._detect_product_boxes") as detect:
        detect.return_value = [
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2} for x1, y1, x2, y2 in fake_boxes
        ]
        bands = build_planogram_sku_band_facings(
            image,
            inventory,
            planogram_items=planogram,
            metadata={},
            scan_context={},
        )

    assert len(bands) == 3
    assert bands[0]["variant"] == "Magic Masala"
    assert bands[0]["annotation_qty"] == 18
    assert bands[1]["annotation_qty"] == 12
    assert bands[2]["annotation_qty"] == 12
    assert bands[0]["y1"] < bands[1]["y1"] < bands[2]["y1"]
