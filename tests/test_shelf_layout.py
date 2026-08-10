"""Tests for shelf layout detection."""

from __future__ import annotations

import numpy as np

from app.shelf_layout import detect_layout


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
