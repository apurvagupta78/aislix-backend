"""Planogram-guided second-pass detection for missed facings (e.g. dark bottles)."""

from __future__ import annotations

import os

import cv2
import numpy as np

from app.detector import deduplicate_boxes, detect_products, get_boxes

YOLO_CONF_GAP_FILL = float(os.getenv("YOLO_CONF_GAP_FILL", "0.10"))
PLANOGRAM_GAP_FILL_ENABLED = os.getenv("PLANOGRAM_GAP_FILL_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
GAP_SLOT_OVERLAP_MIN = float(os.getenv("PLANOGRAM_GAP_SLOT_OVERLAP_MIN", "0.22"))
GAP_REGION_PAD_X = float(os.getenv("PLANOGRAM_GAP_REGION_PAD_X", "0.12"))
GAP_REGION_PAD_Y = float(os.getenv("PLANOGRAM_GAP_REGION_PAD_Y", "0.10"))


def _x_center(box: np.ndarray) -> float:
    return (float(box[0]) + float(box[2])) / 2.0


def _box_width(box: np.ndarray) -> float:
    return max(0.0, float(box[2]) - float(box[0]))


def _box_height(box: np.ndarray) -> float:
    return max(0.0, float(box[3]) - float(box[1]))


def _slot_covered(boxes: list[np.ndarray], slot_x1: float, slot_x2: float) -> bool:
    slot_w = max(slot_x2 - slot_x1, 1.0)
    for box in boxes:
        overlap = min(float(box[2]), slot_x2) - max(float(box[0]), slot_x1)
        if overlap > 0 and overlap / slot_w >= GAP_SLOT_OVERLAP_MIN:
            return True
    return False


def infer_missing_slot_regions(
    boxes: list[np.ndarray],
    expected_count: int,
    image_w: int,
    image_h: int,
) -> list[np.ndarray]:
    """Infer x-regions where a facing is expected but YOLO found nothing."""
    if not boxes or expected_count <= len(boxes):
        return []

    ordered = sorted(boxes, key=_x_center)
    widths = sorted(_box_width(b) for b in ordered)
    heights = sorted(_box_height(b) for b in ordered)
    med_w = widths[len(widths) // 2] or 1.0
    med_h = heights[len(heights) // 2] or 1.0

    row_y1 = max(0.0, min(float(b[1]) for b in ordered) - med_h * GAP_REGION_PAD_Y)
    row_y2 = min(float(image_h), max(float(b[3]) for b in ordered) + med_h * GAP_REGION_PAD_Y)

    span_x1 = min(float(b[0]) for b in ordered)
    span_x2 = max(float(b[2]) for b in ordered)
    pad_x = med_w * GAP_REGION_PAD_X
    grid_x1 = max(0.0, span_x1 - pad_x)
    grid_x2 = min(float(image_w), span_x2 + pad_x)
    slot_width = (grid_x2 - grid_x1) / max(expected_count, 1)

    missing: list[np.ndarray] = []
    for slot_idx in range(expected_count):
        sx1 = grid_x1 + slot_idx * slot_width
        sx2 = sx1 + slot_width
        if _slot_covered(ordered, sx1, sx2):
            continue
        rx1 = max(0.0, sx1 - med_w * 0.08)
        rx2 = min(float(image_w), sx2 + med_w * 0.08)
        missing.append(np.array([rx1, row_y1, rx2, row_y2], dtype=np.float32))

    missing_count = expected_count - len(boxes)
    if len(missing) >= missing_count:
        return missing[:missing_count]

    # Fallback: largest inter-box horizontal gaps (common when one dark bottle is skipped).
    gaps: list[tuple[float, float, float]] = []
    for left, right in zip(ordered, ordered[1:]):
        gap = float(right[0]) - float(left[2])
        if gap > med_w * 0.35:
            mid = (float(left[2]) + float(right[0])) / 2.0
            gaps.append((gap, mid - med_w * 0.5, mid + med_w * 0.5))
    gaps.sort(key=lambda item: item[0], reverse=True)

    seen: set[tuple[int, int, int, int]] = set()
    for _, gx1, gx2 in gaps:
        if len(missing) >= missing_count:
            break
        region = np.array(
            [max(0.0, gx1), row_y1, min(float(image_w), gx2), row_y2],
            dtype=np.float32,
        )
        key = tuple(int(v) for v in region)
        if key in seen:
            continue
        seen.add(key)
        missing.append(region)

    return missing[:missing_count]


def _enhance_dark_crop(crop: np.ndarray) -> np.ndarray:
    """Boost local contrast on dark bottle crops before gap-fill YOLO."""
    if crop.size == 0:
        return crop
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    merged = cv2.merge([l_channel, a_channel, b_channel])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _detect_best_in_region(
    image: np.ndarray,
    region: np.ndarray,
    *,
    conf: float,
) -> np.ndarray | None:
    """Run low-conf YOLO on a crop; return best box in full-image coordinates."""
    h, w = image.shape[:2]
    x1 = int(max(0, min(w - 1, region[0])))
    y1 = int(max(0, min(h - 1, region[1])))
    x2 = int(max(x1 + 1, min(w, region[2])))
    y2 = int(max(y1 + 1, min(h, region[3])))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    best_box: np.ndarray | None = None
    best_score = -1.0
    for source in (crop, _enhance_dark_crop(crop)):
        results, pad_x = detect_products(source, conf=conf)
        local_boxes = get_boxes(results, pad_x=pad_x, max_x=source.shape[1])
        for box in local_boxes:
            full = box.copy()
            full[0] += x1
            full[2] += x1
            full[1] += y1
            full[3] += y1
            area = _box_width(full) * _box_height(full)
            cx = _x_center(full)
            slot_cx = (float(region[0]) + float(region[2])) / 2.0
            slot_w = max(_box_width(region), 1.0)
            center_bonus = max(0.0, 1.0 - abs(cx - slot_cx) / slot_w)
            score = area * (1.0 + center_bonus)
            if score > best_score:
                best_score = score
                best_box = full
        if best_box is not None:
            break
    return best_box


def fill_detection_gaps(
    image: np.ndarray,
    boxes: list[np.ndarray],
    *,
    expected_count: int,
) -> tuple[list[np.ndarray], dict]:
    """Second-pass YOLO on inferred planogram slots when first pass under-detects."""
    stats = {
        "gap_fill_enabled": PLANOGRAM_GAP_FILL_ENABLED,
        "gap_fill_expected": expected_count,
        "gap_fill_initial_boxes": len(boxes),
        "gap_fill_regions": 0,
        "gap_fill_recovered": 0,
    }
    if not PLANOGRAM_GAP_FILL_ENABLED or expected_count <= len(boxes):
        return boxes, stats

    image_h, image_w = image.shape[:2]
    regions = infer_missing_slot_regions(boxes, expected_count, image_w, image_h)
    stats["gap_fill_regions"] = len(regions)
    if not regions:
        return boxes, stats

    recovered: list[np.ndarray] = []
    merged = list(boxes)
    for region in regions:
        found = _detect_best_in_region(image, region, conf=YOLO_CONF_GAP_FILL)
        if found is None:
            continue
        merged.append(found)
        recovered.append(found)
        stats["gap_fill_recovered"] += 1

    if not recovered:
        return boxes, stats

    confidences = [1.0] * len(merged)
    deduped = deduplicate_boxes(merged, confidences)
    stats["gap_fill_final_boxes"] = len(deduped)
    return deduped, stats
