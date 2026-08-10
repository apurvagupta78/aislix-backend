"""Filter duplicate/nested YOLO facings (e.g. bottle cap inside bottle body)."""

from __future__ import annotations

# Only run heavy row-slot dedup on dense multi-row shelves.
ROW_SLOT_DEDUP_MIN_FACINGS = 20


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

    drop = [False] * len(facings)
    for idx_a, a in enumerate(facings):
        if drop[idx_a]:
            continue
        for idx_b in range(idx_a + 1, len(facings)):
            if drop[idx_b]:
                continue
            if not _same_column(a, facings[idx_b]):
                continue
            b = facings[idx_b]
            overlap = (
                _iou(a, b) >= 0.12
                or _containment_ratio(a, b) >= 0.45
                or _containment_ratio(b, a) >= 0.45
                or _is_cap_fragment(a, b)
                or _is_cap_fragment(b, a)
            )
            if not overlap and abs(_x_center(a) - _x_center(b)) > min(_width(a), _width(b)) * 0.25:
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
