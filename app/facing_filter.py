"""Filter duplicate/nested YOLO facings (e.g. bottle cap inside bottle body)."""

from __future__ import annotations

import numpy as np

# Only run heavy row-slot dedup on dense multi-row shelves.
ROW_SLOT_DEDUP_MIN_FACINGS = 20


def _as_box_dict(box) -> dict:
    if isinstance(box, dict):
        return box
    return {
        "x1": float(box[0]),
        "y1": float(box[1]),
        "x2": float(box[2]),
        "y2": float(box[3]),
    }


def _union_box(a: dict, b: dict) -> dict:
    return {
        "x1": min(float(a["x1"]), float(b["x1"])),
        "y1": min(float(a["y1"]), float(b["y1"])),
        "x2": max(float(a["x2"]), float(b["x2"])),
        "y2": max(float(a["y2"]), float(b["y2"])),
    }


def _median_height(items: list[dict]) -> float:
    heights = sorted(_height(item) for item in items if _height(item) > 0)
    if not heights:
        return 0.0
    return heights[len(heights) // 2]


def _same_bottle_column(a: dict, b: dict) -> bool:
    """Same vertical column — allows stacked upper/lower half boxes."""
    if _horizontal_overlap_ratio(a, b) >= 0.28:
        return True
    gap = abs(_x_center(a) - _x_center(b))
    return gap <= min(_width(a), _width(b)) * 0.38


def _is_vertical_stack(a: dict, b: dict, median_h: float) -> bool:
    """True when two boxes are stacked halves of one bottle."""
    if _horizontal_overlap_ratio(a, b) < 0.25:
        return False
    if abs(_x_center(a) - _x_center(b)) > min(_width(a), _width(b)) * 0.38:
        return False
    top, bottom = (a, b) if _y_center(a) < _y_center(b) else (b, a)
    gap_y = float(bottom["y1"]) - float(top["y2"])
    if gap_y > max(_height(top), _height(bottom)) * 0.4:
        return False
    combined_h = float(bottom["y2"]) - float(top["y1"])
    half_h = min(_height(a), _height(b))
    if half_h <= 0:
        return False
    # Each half is ~50–65% of a full bottle; combined is ~1.4–2.4× one half.
    ratio = combined_h / half_h
    if 1.35 <= ratio <= 2.4:
        return True
    if median_h > 0:
        return 0.9 * median_h <= combined_h <= 1.35 * median_h
    return False


def _should_merge_boxes(a: dict, b: dict, median_h: float) -> bool:
    if not _same_bottle_column(a, b):
        return False
    return (
        _is_cap_fragment(a, b)
        or _is_cap_fragment(b, a)
        or _iou(a, b) >= 0.12
        or _containment_ratio(a, b) >= 0.45
        or _containment_ratio(b, a) >= 0.45
        or _is_vertical_stack(a, b, median_h)
    )


def merge_boxes_by_column(boxes: list) -> list:
    """Merge YOLO boxes in the same bottle column before cropping (geometry only)."""
    if len(boxes) <= 1:
        return boxes

    items = [_as_box_dict(box) for box in boxes]
    median_h = _median_height(items)
    changed = True
    while changed:
        changed = False
        drop = [False] * len(items)
        for idx_a in range(len(items)):
            if drop[idx_a]:
                continue
            for idx_b in range(idx_a + 1, len(items)):
                if drop[idx_b]:
                    continue
                if not _should_merge_boxes(items[idx_a], items[idx_b], median_h):
                    continue
                items[idx_a] = _union_box(items[idx_a], items[idx_b])
                drop[idx_b] = True
                changed = True
        items = [item for idx, item in enumerate(items) if not drop[idx]]
        median_h = _median_height(items)

    if isinstance(boxes[0], np.ndarray):
        return [
            np.array([item["x1"], item["y1"], item["x2"], item["y2"]], dtype=boxes[0].dtype)
            for item in items
        ]
    return items


def _area(item: dict) -> float:
    return max(0.0, float(item["x2"]) - float(item["x1"])) * max(
        0.0, float(item["y2"]) - float(item["y1"])
    )


def _height(item: dict) -> float:
    return max(0.0, float(item["y2"]) - float(item["y1"]))


def _width(item: dict) -> float:
    return max(0.0, float(item["x2"]) - float(item["x1"]))


def _x_center(item: dict) -> float:
    return (float(item["x1"]) + float(item["x2"])) / 2.0


def _y_center(item: dict) -> float:
    return (float(item["y1"]) + float(item["y2"])) / 2.0


def _containment_ratio(inner: dict, outer: dict) -> float:
    ix1 = max(float(inner["x1"]), float(outer["x1"]))
    iy1 = max(float(inner["y1"]), float(outer["y1"]))
    ix2 = min(float(inner["x2"]), float(outer["x2"]))
    iy2 = min(float(inner["y2"]), float(outer["y2"]))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    inner_area = _area(inner)
    return inter / inner_area if inner_area > 0 else 0.0


def _horizontal_overlap_ratio(a: dict, b: dict) -> float:
    ix1 = max(float(a["x1"]), float(b["x1"]))
    ix2 = min(float(a["x2"]), float(b["x2"]))
    if ix2 <= ix1:
        return 0.0
    overlap = ix2 - ix1
    narrower = min(_width(a), _width(b))
    return overlap / narrower if narrower > 0 else 0.0


def _iou(a: dict, b: dict) -> float:
    ix1 = max(float(a["x1"]), float(b["x1"]))
    iy1 = max(float(a["y1"]), float(b["y1"]))
    ix2 = min(float(a["x2"]), float(b["x2"]))
    iy2 = min(float(a["y2"]), float(b["y2"]))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _same_row(a: dict, b: dict) -> bool:
    ay1, ay2 = float(a["y1"]), float(a["y2"])
    by1, by2 = float(b["y1"]), float(b["y2"])
    if ay2 <= ay1 or by2 <= by1:
        return True
    acy = (ay1 + ay2) / 2.0
    bcy = (by1 + by2) / 2.0
    row_tol = max(ay2 - ay1, by2 - by1) * 0.55
    return abs(acy - bcy) <= row_tol


def _brand_key(item: dict) -> str:
    return (item.get("brand") or "").strip().lower()


def _is_unknown(item: dict) -> bool:
    return _brand_key(item) in {"", "unknown"}


def _same_column(a: dict, b: dict) -> bool:
    """True when two facings occupy the same bottle column on a shelf row."""
    if not _same_row(a, b):
        return False
    if _horizontal_overlap_ratio(a, b) >= 0.28:
        return True
    gap = abs(_x_center(a) - _x_center(b))
    return gap <= min(_width(a), _width(b)) * 0.38


def _is_cap_fragment(inner: dict, outer: dict) -> bool:
    """True when inner looks like a cap/tag band on top of a bottle body."""
    outer_h = _height(outer)
    if outer_h <= 0:
        return False
    inner_cy = _y_center(inner)
    cap_band = float(outer["y1"]) + outer_h * 0.48
    if inner_cy > cap_band:
        return False
    if _horizontal_overlap_ratio(inner, outer) < 0.30:
        return False
    if _area(inner) / _area(outer) > 0.55:
        return False
    return True


def _pick_preferred(a: dict, b: dict) -> int:
    """Return index to drop between two duplicate facings (0=a, 1=b)."""
    a_unknown = _is_unknown(a)
    b_unknown = _is_unknown(b)
    if a_unknown != b_unknown:
        return 0 if a_unknown else 1
    a_conf = float(a.get("confidence") or 0)
    b_conf = float(b.get("confidence") or 0)
    if abs(a_conf - b_conf) > 0.06:
        return 0 if a_conf < b_conf else 1
    return 0 if _area(a) < _area(b) else 1


def _median_width(facings: list[dict]) -> float:
    widths = sorted(_width(item) for item in facings if _width(item) > 0)
    if not widths:
        return 0.0
    return widths[len(widths) // 2]


def _drop_narrow_unknown_fragments(facings: list[dict]) -> list[dict]:
    """Remove tiny Unknown boxes (cap chips / gap noise between bottles)."""
    median_w = _median_width(facings)
    if median_w <= 0:
        return facings
    min_w = median_w * 0.42
    kept: list[dict] = []
    for item in facings:
        if _is_unknown(item) and _width(item) < min_w:
            continue
        kept.append(item)
    return kept


def _merge_same_column_facings(facings: list[dict]) -> list[dict]:
    """One facing per bottle column — cap + body + phantom duplicates collapse."""
    if len(facings) <= 1:
        return facings

    median_h = _median_height(facings)
    drop = [False] * len(facings)
    for idx_a, a in enumerate(facings):
        if drop[idx_a]:
            continue
        for idx_b in range(idx_a + 1, len(facings)):
            if drop[idx_b]:
                continue
            b = facings[idx_b]
            merge = _should_merge_boxes(a, b, median_h)
            if not merge and _same_column(a, b):
                merge = (
                    _iou(a, b) >= 0.12
                    or _containment_ratio(a, b) >= 0.45
                    or _containment_ratio(b, a) >= 0.45
                    or _is_cap_fragment(a, b)
                    or _is_cap_fragment(b, a)
                )
            if not merge:
                continue
            drop_idx = idx_a if _pick_preferred(a, b) == 0 else idx_b
            drop[drop_idx] = True
            if drop_idx == idx_a:
                a = facings[idx_b]

    return [item for idx, item in enumerate(facings) if not drop[idx]]


def _deduplicate_row_slots(facings: list[dict]) -> list[dict]:
    """Keep one facing per bottle column within each shelf row (multi-row shelves)."""
    if len(facings) <= 1:
        return facings

    heights = sorted(_height(item) for item in facings if _height(item) > 0)
    if not heights:
        return facings
    row_tol = heights[len(heights) // 2] * 0.65

    rows: dict[int, list[tuple[int, dict]]] = {}
    for idx, item in enumerate(facings):
        row_id = int(_y_center(item) // max(row_tol, 1))
        rows.setdefault(row_id, []).append((idx, item))

    drop = [False] * len(facings)
    for row_items in rows.values():
        row_items.sort(key=lambda pair: _x_center(pair[1]))
        cluster: list[tuple[int, dict]] = []
        for idx, item in row_items:
            if not cluster:
                cluster.append((idx, item))
                continue
            prev_idx, prev = cluster[-1]
            if _same_column(prev, item):
                drop_idx = prev_idx if _pick_preferred(prev, item) == 0 else idx
                drop[drop_idx] = True
                if drop_idx == prev_idx:
                    cluster[-1] = (idx, item)
            else:
                cluster.append((idx, item))

    return [item for idx, item in enumerate(facings) if not drop[idx]]


def filter_nested_facings(
    facings: list[dict],
    *,
    containment_threshold: float = 0.68,
    max_inner_area_ratio: float = 0.48,
) -> list[dict]:
    """
    Drop cap/tag fragments nested inside bottle bodies and merge same-column overlaps.
    One physical bottle should produce at most one facing.
    """
    if len(facings) <= 1:
        return facings

    drop = [False] * len(facings)

    # Pass 1: drop smaller facings nested inside a larger neighbor on the same row.
    for inner_idx, inner in enumerate(facings):
        inner_area = _area(inner)
        if inner_area <= 0:
            continue
        for outer_idx, outer in enumerate(facings):
            if inner_idx == outer_idx or drop[inner_idx]:
                continue
            outer_area = _area(outer)
            if outer_area <= inner_area:
                continue
            if not _same_row(inner, outer):
                continue

            nested = (
                inner_area / outer_area <= max_inner_area_ratio
                and _containment_ratio(inner, outer) >= containment_threshold
            )
            if nested or _is_cap_fragment(inner, outer):
                drop[inner_idx] = True

    survivors = [item for idx, item in enumerate(facings) if not drop[idx]]
    survivors = _drop_narrow_unknown_fragments(survivors)
    if len(survivors) <= 1:
        return survivors

    # Pass 2: drop unknown bands in the same column as any labeled bottle.
    drop = [False] * len(survivors)
    for inner_idx, inner in enumerate(survivors):
        if not _is_unknown(inner):
            continue
        for outer_idx, outer in enumerate(survivors):
            if inner_idx == outer_idx or drop[inner_idx]:
                continue
            if _is_unknown(outer):
                continue
            if not _same_column(inner, outer):
                continue
            if _is_cap_fragment(inner, outer) or _area(inner) < _area(outer) * 0.55:
                drop[inner_idx] = True

    survivors = [item for idx, item in enumerate(survivors) if not drop[idx]]
    if len(survivors) <= 1:
        return survivors

    # Pass 3: merge all overlaps in the same bottle column (any brand).
    survivors = _merge_same_column_facings(survivors)

    # Pass 4: row-slot dedup only on dense multi-row shelves.
    if len(survivors) >= ROW_SLOT_DEDUP_MIN_FACINGS:
        survivors = _deduplicate_row_slots(survivors)

    return survivors
