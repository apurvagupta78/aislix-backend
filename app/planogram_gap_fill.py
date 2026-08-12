"""Planogram-guided second-pass detection for missed facings (e.g. dark bottles)."""

from __future__ import annotations

import os

import cv2
import numpy as np

from app.detector import deduplicate_boxes, detect_products, get_boxes

YOLO_CONF_GAP_FILL = float(os.getenv("YOLO_CONF_GAP_FILL", "0.10"))
YOLO_CONF_GAP_FILL_RETRY = float(os.getenv("YOLO_CONF_GAP_FILL_RETRY", "0.06"))
PLANOGRAM_GAP_FILL_ENABLED = os.getenv("PLANOGRAM_GAP_FILL_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
GAP_SLOT_CENTER_MAX = float(os.getenv("PLANOGRAM_GAP_SLOT_CENTER_MAX", "0.62"))
GAP_INTERBOX_CENTER_FACTOR = float(os.getenv("PLANOGRAM_GAP_INTERBOX_CENTER_FACTOR", "1.18"))
GAP_INTERBOX_GAP_FACTOR = float(os.getenv("PLANOGRAM_GAP_INTERBOX_GAP_FACTOR", "0.12"))
GAP_REGION_PAD_X = float(os.getenv("PLANOGRAM_GAP_REGION_PAD_X", "0.12"))
GAP_REGION_PAD_Y = float(os.getenv("PLANOGRAM_GAP_REGION_PAD_Y", "0.10"))


def _x_center(box: np.ndarray) -> float:
    return (float(box[0]) + float(box[2])) / 2.0


def _box_width(box: np.ndarray) -> float:
    return max(0.0, float(box[2]) - float(box[0]))


def _box_height(box: np.ndarray) -> float:
    return max(0.0, float(box[3]) - float(box[1]))


def _row_metrics(boxes: list[np.ndarray], image_h: int) -> tuple[float, float, float, float]:
    ordered = sorted(boxes, key=_x_center)
    widths = sorted(_box_width(b) for b in ordered)
    heights = sorted(_box_height(b) for b in ordered)
    med_w = widths[len(widths) // 2] or 1.0
    med_h = heights[len(heights) // 2] or 1.0
    row_y1 = max(0.0, min(float(b[1]) for b in ordered) - med_h * GAP_REGION_PAD_Y)
    row_y2 = min(float(image_h), max(float(b[3]) for b in ordered) + med_h * GAP_REGION_PAD_Y)
    return med_w, med_h, row_y1, row_y2


def _slot_grid(
    boxes: list[np.ndarray],
    expected_count: int,
    image_w: int,
    med_w: float,
) -> tuple[float, float, float]:
    ordered = sorted(boxes, key=_x_center)
    span_x1 = min(float(b[0]) for b in ordered)
    span_x2 = max(float(b[2]) for b in ordered)
    pad_x = med_w * GAP_REGION_PAD_X
    grid_x1 = max(0.0, span_x1 - pad_x)
    grid_x2 = min(float(image_w), span_x2 + pad_x)
    slot_width = (grid_x2 - grid_x1) / max(expected_count, 1)
    return grid_x1, grid_x2, slot_width


def _slot_centers(grid_x1: float, slot_width: float, expected_count: int) -> list[float]:
    return [grid_x1 + (idx + 0.5) * slot_width for idx in range(expected_count)]


def _occupied_slots_by_center(
    boxes: list[np.ndarray],
    slot_centers: list[float],
    slot_width: float,
) -> set[int]:
    """Assign each box to its nearest slot center (one box per slot)."""
    max_dist = slot_width * GAP_SLOT_CENTER_MAX
    occupied: dict[int, int] = {}
    candidates: list[tuple[float, int, int]] = []
    for box_idx, box in enumerate(boxes):
        cx = _x_center(box)
        for slot_idx, slot_cx in enumerate(slot_centers):
            candidates.append((abs(cx - slot_cx), box_idx, slot_idx))
    candidates.sort(key=lambda item: item[0])

    assigned_boxes: set[int] = set()
    for dist, box_idx, slot_idx in candidates:
        if dist > max_dist:
            continue
        if box_idx in assigned_boxes or slot_idx in occupied:
            continue
        occupied[slot_idx] = box_idx
        assigned_boxes.add(box_idx)

    # Any leftover box (wide/overlapping facings) takes nearest free slot.
    for box_idx, box in enumerate(boxes):
        if box_idx in assigned_boxes:
            continue
        free = [idx for idx in range(len(slot_centers)) if idx not in occupied]
        if not free:
            break
        slot_idx = min(free, key=lambda idx: abs(_x_center(box) - slot_centers[idx]))
        occupied[slot_idx] = box_idx
        assigned_boxes.add(box_idx)

    return set(occupied.keys())


def _region_for_slot(
    slot_idx: int,
    grid_x1: float,
    slot_width: float,
    med_w: float,
    row_y1: float,
    row_y2: float,
    image_w: int,
) -> np.ndarray:
    sx1 = grid_x1 + slot_idx * slot_width
    sx2 = sx1 + slot_width
    rx1 = max(0.0, sx1 - med_w * 0.10)
    rx2 = min(float(image_w), sx2 + med_w * 0.10)
    return np.array([rx1, row_y1, rx2, row_y2], dtype=np.float32)


def _inter_box_probe_regions(
    boxes: list[np.ndarray],
    *,
    med_w: float,
    row_y1: float,
    row_y2: float,
    image_w: int,
    limit: int,
) -> list[np.ndarray]:
    """Probe midpoints between facings when center spacing suggests a skipped product."""
    ordered = sorted(boxes, key=_x_center)
    probes: list[tuple[float, np.ndarray]] = []
    for left, right in zip(ordered, ordered[1:]):
        gap = float(right[0]) - float(left[2])
        center_gap = _x_center(right) - _x_center(left)
        if gap > med_w * GAP_INTERBOX_GAP_FACTOR or center_gap > med_w * GAP_INTERBOX_CENTER_FACTOR:
            mid = (_x_center(left) + _x_center(right)) / 2.0
            half = med_w * 0.55
            region = np.array(
                [max(0.0, mid - half), row_y1, min(float(image_w), mid + half), row_y2],
                dtype=np.float32,
            )
            probes.append((center_gap, region))

    probes.sort(key=lambda item: item[0], reverse=True)
    return [region for _, region in probes[:limit]]


def _dedupe_regions(regions: list[np.ndarray], med_w: float) -> list[np.ndarray]:
    if not regions:
        return []
    unique: list[np.ndarray] = []
    min_sep = med_w * 0.35
    for region in sorted(regions, key=lambda r: float(r[0])):
        cx = (float(region[0]) + float(region[2])) / 2.0
        if any(abs(cx - (float(u[0]) + float(u[2])) / 2.0) < min_sep for u in unique):
            continue
        unique.append(region)
    return unique


def infer_missing_slot_regions(
    boxes: list[np.ndarray],
    expected_count: int,
    image_w: int,
    image_h: int,
) -> list[np.ndarray]:
    """Infer x-regions where a facing is expected but YOLO found nothing."""
    if not boxes or expected_count <= len(boxes):
        return []

    med_w, _, row_y1, row_y2 = _row_metrics(boxes, image_h)
    grid_x1, grid_x2, slot_width = _slot_grid(boxes, expected_count, image_w, med_w)
    slot_centers = _slot_centers(grid_x1, slot_width, expected_count)
    occupied = _occupied_slots_by_center(boxes, slot_centers, slot_width)
    missing_count = expected_count - len(boxes)

    missing: list[np.ndarray] = []
    for slot_idx in range(expected_count):
        if slot_idx in occupied:
            continue
        missing.append(
            _region_for_slot(slot_idx, grid_x1, slot_width, med_w, row_y1, row_y2, image_w)
        )

    if len(missing) < missing_count:
        missing.extend(
            _inter_box_probe_regions(
                boxes,
                med_w=med_w,
                row_y1=row_y1,
                row_y2=row_y2,
                image_w=image_w,
                limit=missing_count - len(missing),
            )
        )

    return _dedupe_regions(missing, med_w)[:missing_count]


def _enhance_dark_crop(crop: np.ndarray) -> np.ndarray:
    """Boost local contrast on dark bottle/carton crops before gap-fill YOLO."""
    if crop.size == 0:
        return crop
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    merged = cv2.merge([l_channel, a_channel, b_channel])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _brighten_dark_crop(crop: np.ndarray) -> np.ndarray:
    if crop.size == 0:
        return crop
    gamma = 0.65
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(crop, table)


def _maybe_upscale(crop: np.ndarray, min_width: int = 180) -> np.ndarray:
    h, w = crop.shape[:2]
    if w >= min_width:
        return crop
    scale = min_width / max(w, 1)
    return cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _detect_boxes_in_source(
    source: np.ndarray,
    offset_x: int,
    offset_y: int,
    *,
    conf: float,
    max_x: int,
) -> list[np.ndarray]:
    results, pad_x = detect_products(source, conf=conf)
    local_boxes = get_boxes(results, pad_x=pad_x, max_x=source.shape[1])
    full_boxes: list[np.ndarray] = []
    for box in local_boxes:
        full = box.copy()
        full[0] += offset_x
        full[2] += offset_x
        full[1] += offset_y
        full[3] += offset_y
        full[0] = max(0.0, full[0])
        full[2] = min(float(max_x), full[2])
        full_boxes.append(full)
    return full_boxes


def _score_candidate(box: np.ndarray, region: np.ndarray) -> float:
    area = _box_width(box) * _box_height(box)
    cx = _x_center(box)
    slot_cx = (float(region[0]) + float(region[2])) / 2.0
    slot_w = max(_box_width(region), 1.0)
    center_bonus = max(0.0, 1.0 - abs(cx - slot_cx) / slot_w)
    return area * (1.0 + center_bonus * 1.5)


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
    sources = (
        crop,
        _enhance_dark_crop(crop),
        _brighten_dark_crop(crop),
        _maybe_upscale(_enhance_dark_crop(crop)),
    )
    confs = (conf, YOLO_CONF_GAP_FILL_RETRY)
    for source in sources:
        for try_conf in confs:
            for box in _detect_boxes_in_source(
                source, x1, y1, conf=try_conf, max_x=w
            ):
                score = _score_candidate(box, region)
                if score > best_score:
                    best_score = score
                    best_box = box
        if best_box is not None:
            break
    return best_box


def _recover_from_row_strip(
    image: np.ndarray,
    boxes: list[np.ndarray],
    regions: list[np.ndarray],
    *,
    expected_count: int,
) -> list[np.ndarray]:
    """Last resort: low-conf detect on the full shelf row, keep boxes near empty slots."""
    if not regions or expected_count <= len(boxes):
        return []

    image_h, image_w = image.shape[:2]
    med_w, _, row_y1, row_y2 = _row_metrics(boxes, image_h)
    y1 = int(max(0, row_y1))
    y2 = int(min(image_h, row_y2))
    strip = image[y1:y2, :]
    if strip.size == 0:
        return []

    target_centers = [
        (float(r[0]) + float(r[2])) / 2.0 for r in regions
    ]
    recovered: list[np.ndarray] = []
    seen_centers: list[float] = []

    for source in (strip, _enhance_dark_crop(strip), _brighten_dark_crop(strip)):
        for conf in (YOLO_CONF_GAP_FILL, YOLO_CONF_GAP_FILL_RETRY):
            candidates = _detect_boxes_in_source(source, 0, y1, conf=conf, max_x=image_w)
            for box in candidates:
                cx = _x_center(box)
                if any(abs(cx - existing) < med_w * 0.35 for existing in seen_centers):
                    continue
                if not any(abs(cx - tc) <= med_w * 0.75 for tc in target_centers):
                    continue
                overlaps = False
                for existing in boxes + recovered:
                    ix1 = max(float(box[0]), float(existing[0]))
                    ix2 = min(float(box[2]), float(existing[2]))
                    if ix2 - ix1 > med_w * 0.35:
                        overlaps = True
                        break
                if overlaps:
                    continue
                recovered.append(box)
                seen_centers.append(cx)
                if len(recovered) >= len(regions):
                    return recovered
        if recovered:
            break
    return recovered


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
        "gap_fill_row_strip": 0,
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

    missing_after = expected_count - len(merged)
    if missing_after > 0:
        unresolved = regions[len(recovered) :]
        if not unresolved:
            unresolved = regions
        strip_found = _recover_from_row_strip(
            image,
            merged,
            unresolved[:missing_after],
            expected_count=expected_count,
        )
        for box in strip_found:
            merged.append(box)
            recovered.append(box)
            stats["gap_fill_row_strip"] += 1
            stats["gap_fill_recovered"] += 1

    if not recovered:
        return boxes, stats

    confidences = [1.0] * len(merged)
    deduped = deduplicate_boxes(merged, confidences)
    stats["gap_fill_final_boxes"] = len(deduped)
    return deduped, stats
