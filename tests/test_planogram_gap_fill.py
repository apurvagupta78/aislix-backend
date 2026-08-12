"""Tests for planogram-guided gap-fill detection."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.planogram_gap_fill import (
    _occupied_slots_by_center,
    _slot_centers,
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
    mid_x = (float(regions[0][0]) + float(regions[0][2])) / 2.0
    assert 300 <= mid_x <= 420


def test_infer_missing_slot_wide_neighbor_does_not_block_empty_slot():
    """Wide box overlapping next slot must not mark that slot as covered (TRESemmé case)."""
    boxes = _synthetic_row_boxes(8, skip_index=1)
    boxes[0][2] = boxes[0][0] + 80.0 * 1.75
    regions = infer_missing_slot_regions(boxes, expected_count=8, image_w=700, image_h=300)
    assert len(regions) >= 1
    mid_x = (float(regions[0][0]) + float(regions[0][2])) / 2.0
    assert 90 <= mid_x <= 190


def test_infer_missing_two_gaps_in_seven_slot_row():
    """Tea row: two dark cartons skipped in the middle of a 7-SKU planogram."""
    boxes = _synthetic_row_boxes(7, skip_index=4)
    boxes = [b for i, b in enumerate(_synthetic_row_boxes(7)) if i not in {4, 5}]
    regions = infer_missing_slot_regions(boxes, expected_count=7, image_w=620, image_h=300)
    assert len(regions) == 2


def test_center_assignment_one_box_per_slot():
    grid_x1, slot_width = 20.0, 80.0
    centers = _slot_centers(grid_x1, slot_width, 8)
    boxes = _synthetic_row_boxes(8, skip_index=1)
    boxes[0][2] = boxes[0][0] + 80.0 * 1.75
    occupied = _occupied_slots_by_center(boxes, centers, slot_width)
    assert 1 not in occupied


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


def test_fill_detection_gaps_uses_synthetic_when_yolo_misses():
    image = np.zeros((300, 700, 3), dtype=np.uint8)
    boxes = _synthetic_row_boxes(8, skip_index=4)

    with patch("app.planogram_gap_fill.detect_products") as mock_detect:
        mock_detect.return_value = ([], 0)
        with patch("app.planogram_gap_fill.get_boxes") as mock_boxes:
            mock_boxes.return_value = []
            merged, stats = fill_detection_gaps(image, boxes, expected_count=8)

    assert stats["gap_fill_synthetic"] >= 1
    assert len(merged) == 8


def test_fill_detection_gaps_noop_without_planogram_shortfall():
    boxes = _synthetic_row_boxes(8)
    image = np.zeros((300, 700, 3), dtype=np.uint8)
    merged, stats = fill_detection_gaps(image, boxes, expected_count=8)
    assert merged == boxes
    assert stats["gap_fill_recovered"] == 0
