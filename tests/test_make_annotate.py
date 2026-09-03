"""Tests for Make.com local YOLO annotation label assignment."""

from __future__ import annotations

import numpy as np

from app.make_annotate import (
    _assign_inventory_to_boxes,
    _bands_from_shelf_rows,
    _filter_product_zone_boxes,
    _proportional_row_counts,
    build_sku_band_facings,
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


def test_build_sku_band_facings_one_box_per_sku_with_qty():
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
    bands = build_sku_band_facings(image, inventory, planogram_items=planogram)
    assert len(bands) == 3
    assert bands[0]["variant"] == "Magic Masala"
    assert bands[0]["annotation_qty"] == 18
    assert bands[1]["annotation_qty"] == 12
    assert bands[2]["annotation_qty"] == 12
    assert bands[0]["y1"] < bands[1]["y1"] < bands[2]["y1"]


def test_build_sku_band_facings_ignores_untrusted_gpt_bboxes_by_default():
    """GPT bbox spans must not drive band placement unless explicitly enabled."""
    image = np.zeros((1000, 800, 3), dtype=np.uint8)
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 16},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 12},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 8},
    ]
    planogram = [
        {"brand": "Lays", "variant": "Magic Masala", "expected_qty": 19},
        {"brand": "Lays", "variant": "Tomato tango", "expected_qty": 6},
        {"brand": "Lays", "variant": "American cream and onion", "expected_qty": 12},
    ]
    # Swapped vertical GPT boxes — would mislabel if used for layout.
    openai_facings = [
        {
            "brand": "Lays",
            "product_name": "Potato Chips",
            "variant": "Magic Masala",
            "x1": 40,
            "y1": 500,
            "x2": 760,
            "y2": 700,
        },
        {
            "brand": "Lays",
            "product_name": "Potato Chips",
            "variant": "Tomato tango",
            "x1": 40,
            "y1": 120,
            "x2": 760,
            "y2": 320,
        },
        {
            "brand": "Lays",
            "product_name": "Potato Chips",
            "variant": "American cream and onion",
            "x1": 40,
            "y1": 720,
            "x2": 760,
            "y2": 920,
        },
    ]
    bands = build_sku_band_facings(
        image,
        inventory,
        planogram_items=planogram,
        openai_facings=openai_facings,
    )
    assert len(bands) == 3
    assert bands[0]["variant"] == "Magic Masala"
    assert bands[1]["variant"] == "Tomato tango"
    assert bands[0]["y1"] < bands[1]["y1"] < bands[2]["y1"]


def test_assign_rows_by_gpt_bbox_overlap_labels_correct_sku():
    from app.make_annotate import _assign_rows_by_gpt_bbox_overlap, _bands_from_shelf_rows_with_gpt_labels

    row_bounds = [
        {"x1": 50, "y1": 150, "x2": 700, "y2": 230},
        {"x1": 50, "y1": 240, "x2": 700, "y2": 320},
        {"x1": 50, "y1": 330, "x2": 700, "y2": 410},
        {"x1": 50, "y1": 420, "x2": 700, "y2": 500},
        {"x1": 50, "y1": 510, "x2": 700, "y2": 590},
        {"x1": 50, "y1": 600, "x2": 700, "y2": 680},
    ]
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 16},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 12},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 8},
    ]
    product_rows = [
        {
            "brand": "Lays",
            "product": "Potato Chips",
            "variant": "Magic Masala",
            "qty": 16,
            "bbox_2d": [40, 150, 960, 420],
        },
        {
            "brand": "Lays",
            "product": "Potato Chips",
            "variant": "Tomato tango",
            "qty": 12,
            "bbox_2d": [40, 430, 960, 560],
        },
        {
            "brand": "Lays",
            "product": "Potato Chips",
            "variant": "American cream and onion",
            "qty": 8,
            "bbox_2d": [40, 580, 960, 760],
        },
    ]
    image_shape = (800, 900, 3)
    assignments = _assign_rows_by_gpt_bbox_overlap(row_bounds, product_rows, inventory, image_shape)
    assert len(assignments) == 6
    assert assignments[0][1]["variant"] == "Magic Masala"
    assert assignments[3][1]["variant"] == "Tomato tango"
    assert assignments[4][1]["variant"] == "American cream and onion"

    planogram = [
        {"brand": "Lays", "variant": "Magic Masala", "expected_qty": 19},
        {"brand": "Lays", "variant": "Tomato tango", "expected_qty": 6},
        {"brand": "Lays", "variant": "American cream and onion", "expected_qty": 12},
    ]
    bands = _bands_from_shelf_rows_with_gpt_labels(
        row_bounds,
        inventory,
        product_rows,
        image_shape,
        img_w=900,
        planogram_items=planogram,
    )
    assert len(bands) == 3
    assert bands[0]["variant"] == "Magic Masala"
    assert bands[1]["variant"] == "Tomato tango"
    assert bands[2]["variant"] == "American cream and onion"


def test_bands_from_shelf_rows_lays_planogram_three_bands():
    """Lay's rack: 6 detected rows → 3 SKU bands (3+1+2 rows) in planogram order."""
    row_bounds = [
        {"x1": 50, "y1": 150, "x2": 700, "y2": 230},
        {"x1": 50, "y1": 240, "x2": 700, "y2": 320},
        {"x1": 50, "y1": 330, "x2": 700, "y2": 410},
        {"x1": 50, "y1": 420, "x2": 700, "y2": 500},
        {"x1": 50, "y1": 510, "x2": 700, "y2": 590},
        {"x1": 50, "y1": 600, "x2": 700, "y2": 680},
    ]
    inventory = [
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Magic Masala", "quantity": 18},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "Tomato tango", "quantity": 12},
        {"brand": "Lays", "product_name": "Potato Chips", "variant": "American cream and onion", "quantity": 12},
    ]
    weights = [19, 6, 12]
    bands = _bands_from_shelf_rows(inventory, row_bounds, weights, img_w=800)
    assert len(bands) == 3
    assert bands[0]["variant"] == "Magic Masala"
    assert bands[0]["y1"] == 150
    assert bands[0]["y2"] == 410
    assert bands[1]["variant"] == "Tomato tango"
    assert bands[1]["y1"] == 420
    assert bands[2]["variant"] == "American cream and onion"
    assert bands[2]["y1"] == 510


def test_build_sku_band_facings_toothpaste_many_skus():
    image = np.zeros((1200, 800, 3), dtype=np.uint8)
    inventory = [
        {"brand": "Colgate", "product_name": "Toothpaste", "variant": "Triple Acción", "quantity": 24},
        {"brand": "Oral-B", "product_name": "Toothpaste", "variant": "Complete", "quantity": 16},
        {"brand": "Colgate", "product_name": "Toothpaste", "variant": "Total 12", "quantity": 12},
    ]
    bands = build_sku_band_facings(image, inventory)
    assert len(bands) == 3
    assert bands[0]["variant"] == "Triple Acción"
    assert bands[0]["annotation_qty"] == 24
    assert bands[0]["brand"] == "Colgate"
