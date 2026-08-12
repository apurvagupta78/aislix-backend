"""Box matching metrics for shelf detection benchmarks."""

from __future__ import annotations

import numpy as np

from app.detector import _box_iou


def _as_box(box) -> np.ndarray:
    if isinstance(box, dict):
        return np.array(
            [float(box["x1"]), float(box["y1"]), float(box["x2"]), float(box["y2"])],
            dtype=np.float32,
        )
    arr = np.asarray(box, dtype=np.float32)
    return arr.reshape(4)


def match_boxes(
    predicted: list,
    ground_truth: list,
    *,
    iou_threshold: float = 0.5,
) -> dict:
    """Greedy IoU matching: one pred per GT box."""
    preds = [_as_box(b) for b in predicted]
    gts = [_as_box(b) for b in ground_truth]

    if not gts:
        return {
            "true_positives": 0,
            "false_positives": len(preds),
            "false_negatives": 0,
            "precision": 1.0 if not preds else 0.0,
            "recall": 1.0,
            "facing_count_error": len(preds),
        }

    pairs: list[tuple[float, int, int]] = []
    for pi, pred in enumerate(preds):
        for gi, gt in enumerate(gts):
            iou = _box_iou(pred, gt)
            if iou >= iou_threshold:
                pairs.append((iou, pi, gi))
    pairs.sort(key=lambda item: item[0], reverse=True)

    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    for _, pi, gi in pairs:
        if pi in matched_pred or gi in matched_gt:
            continue
        matched_pred.add(pi)
        matched_gt.add(gi)

    tp = len(matched_gt)
    fp = len(preds) - len(matched_pred)
    fn = len(gts) - len(matched_gt)
    precision = tp / max(len(preds), 1)
    recall = tp / len(gts)

    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "facing_count_error": len(preds) - len(gts),
        "predicted_count": len(preds),
        "ground_truth_count": len(gts),
    }


def aggregate_detection_metrics(case_results: list[dict]) -> dict:
    total_gt = sum(r["ground_truth_count"] for r in case_results)
    total_tp = sum(r["true_positives"] for r in case_results)
    total_pred = sum(r["predicted_count"] for r in case_results)
    return {
        "cases": len(case_results),
        "facing_recall": round(total_tp / max(total_gt, 1), 4),
        "facing_precision": round(total_tp / max(total_pred, 1), 4),
        "total_ground_truth_facings": total_gt,
        "total_predicted_facings": total_pred,
        "total_true_positives": total_tp,
    }
