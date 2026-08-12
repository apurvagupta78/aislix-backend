"""Tests for SAHI tiling and benchmark metrics."""

from __future__ import annotations

import numpy as np

from app.benchmark_metrics import aggregate_detection_metrics, match_boxes
from app.sahi_detector import generate_slice_windows


def test_generate_slice_windows_covers_wide_image():
    windows = generate_slice_windows(800, 2400, tile_size=640, overlap_ratio=0.25)
    assert len(windows) >= 3
    # Full width covered
    assert min(w[0] for w in windows) == 0
    assert max(w[2] for w in windows) == 2400


def test_generate_slice_windows_single_tile_for_small_image():
    windows = generate_slice_windows(400, 500, tile_size=640, overlap_ratio=0.25)
    assert windows == [(0, 0, 500, 400)]


def test_match_boxes_perfect_overlap():
    box = [10.0, 10.0, 50.0, 100.0]
    metrics = match_boxes([box], [box], iou_threshold=0.5)
    assert metrics["true_positives"] == 1
    assert metrics["recall"] == 1.0
    assert metrics["precision"] == 1.0


def test_match_boxes_one_miss():
    gt = [np.array([10.0, 10.0, 50.0, 100.0]), np.array([60.0, 10.0, 100.0, 100.0])]
    pred = [np.array([12.0, 12.0, 48.0, 98.0])]
    metrics = match_boxes(pred, gt, iou_threshold=0.5)
    assert metrics["true_positives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["recall"] == 0.5


def test_aggregate_detection_metrics():
    cases = [
        {"true_positives": 7, "predicted_count": 7, "ground_truth_count": 8},
        {"true_positives": 5, "predicted_count": 5, "ground_truth_count": 7},
    ]
    agg = aggregate_detection_metrics(cases)
    assert agg["total_true_positives"] == 12
    assert agg["total_ground_truth_facings"] == 15
    assert round(agg["facing_recall"], 2) == 0.8
