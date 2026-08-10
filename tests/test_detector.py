"""Tests for YOLO box deduplication."""

from __future__ import annotations

import numpy as np

from app.detector import deduplicate_boxes


def test_deduplicate_overlapping_same_row():
    boxes = [
        np.array([10.0, 10.0, 50.0, 100.0]),
        np.array([12.0, 12.0, 48.0, 98.0]),
        np.array([200.0, 10.0, 240.0, 100.0]),
    ]
    confidences = [0.9, 0.7, 0.85]
    deduped = deduplicate_boxes(boxes, confidences, iou_threshold=0.55)
    assert len(deduped) == 2


def test_deduplicate_keeps_separate_rows():
    boxes = [
        np.array([10.0, 10.0, 50.0, 100.0]),
        np.array([12.0, 120.0, 48.0, 210.0]),
    ]
    deduped = deduplicate_boxes(boxes, [0.9, 0.9], iou_threshold=0.55)
    assert len(deduped) == 2
