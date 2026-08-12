"""Tests for planogram-guided gap-fill detection."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from app.planogram_gap_fill import (
    fill_detection_gaps,
    infer_missing_slot_regions,
)


def _synthetic_row_boxes(count: int, *, skip_index: int | None = None) -> list[np.ndarray]:
    """Evenly spaced facings; optionally omit one slot."""
    boxes: list[np.ndarray] = []
    slot_w = 80.0
    y1, y2 = 40.0, 200.0
    for idx in range(count):
        if skip_index is not None and idx == skip_index:
            continue
        x1 = 20.0 + idx * slot_w
        boxes.append(np.array([x1, y1, x1 + slot_w - 8, y2], dtype=np.float32))
    return boxes


def test_infer_missing_slot_one_gap_in_eight_slot_row():
    boxes = _synthetic_row_boxes(8, skip_index=4)
    regions = infer_missing_slot_regions(boxes, expected_count=8, image_w=700, image_h=300)
    assert len(regions) >= 1
    # Missing slot is index 4 → center around x ≈ 20 + 4*80 + 40 = 360
    mid_x = (float(regions[0][0]) + float(regions[0][2])) / 2.0
    assert 300 <= mid_x <= 420


def test_infer_missing_slot_returns_empty_when_full():
    boxes = _synthetic_row_boxes(8)
    regions = infer_missing_slot_regions(boxes, expected_count=8, image_w=700, image_h=300)
    assert regions == []


def test_fill_detection_gaps_recovers_mocked_box():
    image = np.zeros((300, 700, 3), dtype=np.uint8)
    boxes = _synthetic_row_boxes(8, skip_index=4)
    fake_local = np.array([10.0, 20.0, 60.0, 140.0], dtype=np.float32)

    with patch("app.planogram_gap_fill.detect_products") as mock_detect:
        mock_detect.return_value = ([], 0)
        with patch("app.planogram_gap_fill.get_boxes") as mock_boxes:
            mock_boxes.return_value = [fake_local]

            merged, stats = fill_detection_gaps(image, boxes, expected_count=8)

    assert stats["gap_fill_recovered"] >= 1
    assert len(merged) >= len(boxes) + 1


def test_fill_detection_gaps_noop_without_planogram_shortfall():
    boxes = _synthetic_row_boxes(8)
    image = np.zeros((300, 700, 3), dtype=np.uint8)
    merged, stats = fill_detection_gaps(image, boxes, expected_count=8)
    assert merged == boxes
    assert stats["gap_fill_recovered"] == 0
