"""Shared helpers for cross-category accuracy benchmarks and labeling pipelines."""

from __future__ import annotations

import re
from typing import Any

from app.benchmark_metrics import match_boxes


def resolve_facing_box(facing: dict, width: int, height: int) -> list[int]:
    """Pixel box [x1,y1,x2,y2] from normalized or absolute facing dict."""
    box = facing.get("box") or facing.get("bbox") or [0, 0, 0, 0]
    if len(box) != 4:
        return [0, 0, 0, 0]
    if all(isinstance(v, (int, float)) and 0 <= float(v) <= 1 for v in box):
        return [
            int(float(box[0]) * width),
            int(float(box[1]) * height),
            int(float(box[2]) * width),
            int(float(box[3]) * height),
        ]
    return [int(box[0]), int(box[1]), int(box[2]), int(box[3])]


def facing_record_from_box(box: list[int]) -> dict[str, int]:
    return {"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]}


def normalize_label_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def character_error_rate(expected: str, actual: str) -> float:
    """Levenshtein CER in [0, 1]. Empty expected → 0 if actual empty else 1."""
    exp = normalize_label_text(expected)
    act = normalize_label_text(actual)
    if not exp:
        return 0.0 if not act else 1.0
    if not act:
        return 1.0

    rows = len(exp) + 1
    cols = len(act) + 1
    dist = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dist[i][0] = i
    for j in range(cols):
        dist[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if exp[i - 1] == act[j - 1] else 1
            dist[i][j] = min(
                dist[i - 1][j] + 1,
                dist[i][j - 1] + 1,
                dist[i - 1][j - 1] + cost,
            )
    return dist[rows - 1][cols - 1] / len(exp)


def brand_match(expected: str, actual: str) -> bool:
    exp = normalize_label_text(expected)
    act = normalize_label_text(actual)
    if not exp:
        return True
    exp_key = re.sub(r"[^a-z0-9]", "", exp)
    act_key = re.sub(r"[^a-z0-9]", "", act)
    return exp == act or exp in act or act in exp or (exp_key and exp_key in act_key)


def product_match(expected: str, actual: str) -> bool:
    exp = normalize_label_text(expected)
    act = normalize_label_text(actual)
    if not exp:
        return True
    if exp in act or act in exp:
        return True
    exp_tokens = set(exp.split())
    act_tokens = set(act.split())
    if not exp_tokens:
        return True
    overlap = len(exp_tokens & act_tokens) / len(exp_tokens)
    return overlap >= 0.5


def sku_match(expected: str, actual: str) -> bool:
    exp = normalize_label_text(expected).replace(" ", "_")
    act = normalize_label_text(actual).replace(" ", "_")
    if not exp:
        return True
    return exp == act or exp in act or act in exp


def expected_ocr_label(facing: dict) -> str:
    label = (facing.get("ocr_label") or facing.get("product_name") or "").strip()
    brand = (facing.get("brand") or "").strip()
    if brand and brand.lower() not in label.lower():
        label = f"{brand} {label}".strip()
    return label


def case_scan_context(case: dict) -> dict[str, Any]:
    return {
        "aislix_category": case.get("category"),
        "sub_category": case.get("sub_category"),
        "location": case.get("location"),
    }


def category_key(case: dict) -> str:
    sub = (case.get("sub_category") or "").strip()
    if sub:
        return sub
    category = (case.get("category") or "general").strip()
    if "·" in category:
        return category.split("·")[-1].strip().lower().replace(" ", "_")
    return category.lower().replace(" ", "_")


def aggregate_rates(rows: list[dict], field: str) -> float:
    if not rows:
        return 0.0
    ok = sum(1 for row in rows if row.get(field))
    return round(100.0 * ok / len(rows), 1)


def aggregate_cer(rows: list[dict]) -> float:
    scores = [float(row["cer"]) for row in rows if row.get("cer") is not None]
    if not scores:
        return 0.0
    return round(100.0 * sum(scores) / len(scores), 1)


def match_predicted_to_ground_truth(
    predicted: list[dict],
    ground_truth: list[dict],
    *,
    width: int,
    height: int,
    iou_threshold: float = 0.5,
) -> list[dict]:
    """Pair GT facings with predicted facings by greedy IoU."""
    gt_boxes = [resolve_facing_box(f, width, height) for f in ground_truth]
    pred_boxes = []
    for pred in predicted:
        if "x1" in pred:
            pred_boxes.append(
                [int(pred["x1"]), int(pred["y1"]), int(pred["x2"]), int(pred["y2"])]
            )
        else:
            pred_boxes.append(resolve_facing_box(pred, width, height))

    pairs: list[tuple[float, int, int]] = []
    for pi, pred_box in enumerate(pred_boxes):
        for gi, gt_box in enumerate(gt_boxes):
            if gt_box == [0, 0, 0, 0]:
                continue
            from app.detector import _box_iou
            import numpy as np

            iou = float(_box_iou(np.asarray(pred_box, dtype=np.float32), np.asarray(gt_box, dtype=np.float32)))
            if iou >= iou_threshold:
                pairs.append((iou, pi, gi))
    pairs.sort(key=lambda item: item[0], reverse=True)

    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    results: list[dict] = []
    for iou, pi, gi in pairs:
        if pi in matched_pred or gi in matched_gt:
            continue
        matched_pred.add(pi)
        matched_gt.add(gi)
        gt = ground_truth[gi]
        pred = predicted[pi]
        results.append(
            {
                "gt_id": gt.get("id"),
                "iou": round(iou, 3),
                "expected_brand": gt.get("brand") or "",
                "expected_product": gt.get("product_name") or "",
                "expected_sku": gt.get("sku") or "",
                "got_brand": pred.get("brand") or "",
                "got_product": pred.get("product_name") or "",
                "got_sku": pred.get("sku") or "",
                "brand_ok": brand_match(gt.get("brand") or "", pred.get("brand") or ""),
                "product_ok": product_match(gt.get("product_name") or "", pred.get("product_name") or ""),
                "sku_ok": sku_match(gt.get("sku") or "", pred.get("sku") or ""),
                "recognition_source": pred.get("recognition_source"),
                "ocr_confidence": pred.get("ocr_confidence"),
            }
        )
    return results


def detection_metrics_for_case(
    predicted_boxes: list,
    case: dict,
    *,
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    gt_boxes = []
    for facing in case.get("facings") or []:
        box = facing.get("box")
        if box and len(box) == 4:
            gt_boxes.append(box)
    stats = match_boxes(predicted_boxes, gt_boxes, iou_threshold=iou_threshold)
    expected_count = int(case.get("expected_facing_count") or len(gt_boxes) or 0)
    stats["expected_facing_count"] = expected_count
    stats["count_error"] = abs(stats["predicted_count"] - expected_count)
    return stats
