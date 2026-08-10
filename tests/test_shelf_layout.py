"""Tests for shelf layout detection."""

from __future__ import annotations

import numpy as np

from app.shelf_layout import detect_layout, detect_shelf_mode


def test_single_row_shampoo_like_boxes():
    boxes = [
        np.array([10.0, 100.0, 60.0, 250.0]),
        np.array([80.0, 105.0, 130.0, 255.0]),
        np.array([150.0, 98.0, 200.0, 248.0]),
        np.array([220.0, 102.0, 270.0, 252.0]),
    ]
    assert detect_layout(boxes, image_h=400) == "single_row"


def test_multi_row_mixed_shelf_boxes():
    boxes = [
        np.array([10.0, 20.0, 60.0, 120.0]),
        np.array([10.0, 150.0, 60.0, 250.0]),
        np.array([10.0, 280.0, 60.0, 380.0]),
        np.array([10.0, 410.0, 60.0, 510.0]),
        np.array([80.0, 25.0, 130.0, 125.0]),
        np.array([80.0, 155.0, 130.0, 255.0]),
    ]
    assert detect_layout(boxes, image_h=600) == "multi_row"


def test_close_up_bin_detected_from_over_segmentation():
    """15 cap/body fragments on one row → single_bin mode."""
    boxes = []
    for i in range(8):
        x = 20 + i * 70
        boxes.append(np.array([float(x), 120.0, float(x + 30), 200.0]))
        boxes.append(np.array([float(x + 2), 80.0, float(x + 28), 125.0]))
    boxes.append(np.array([580.0, 100.0, 610.0, 190.0]))
    assert detect_shelf_mode(boxes, image_h=400, image_w=640) == "single_bin"


def test_full_rack_single_row_not_single_bin():
    """Small facings on one row of a wide rack → single_row, not single_bin."""
    boxes = [np.array([10.0 + i * 25, 50.0, 28.0 + i * 25, 110.0]) for i in range(20)]
    assert detect_shelf_mode(boxes, image_h=800, image_w=1200) == "single_row"
