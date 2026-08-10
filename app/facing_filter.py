"""Filter duplicate/nested YOLO facings (e.g. bottle cap inside bottle body)."""

from __future__ import annotations


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


def _is_cap_fragment(inner: dict, outer: dict) -> bool:
    """True when inner looks like a cap/tag band on top of a bottle body."""
    outer_h = _height(outer)
    if outer_h <= 0:
        return False
    inner_cy = _y_center(inner)
    cap_band = float(outer["y1"]) + outer_h * 0.45
    if inner_cy > cap_band:
        return False
    if _horizontal_overlap_ratio(inner, outer) < 0.35:
        return False
    if _area(inner) / _area(outer) > 0.5:
        return False
    return True


def _pick_preferred(a: dict, b: dict) -> int:
    """Return index to drop between two duplicate facings (0=a, 1=b)."""
    a_area = _area(a)
    b_area = _area(b)
    a_conf = float(a.get("confidence") or 0)
    b_conf = float(b.get("confidence") or 0)
    a_unknown = _brand_key(a) in {"", "unknown"}
    b_unknown = _brand_key(b) in {"", "unknown"}
    if a_unknown != b_unknown:
        return 0 if a_unknown else 1
    if abs(a_conf - b_conf) > 0.08:
        return 0 if a_conf < b_conf else 1
    return 0 if a_area < b_area else 1


def _deduplicate_row_slots(facings: list[dict]) -> list[dict]:
    """Keep one facing per bottle column within each shelf row."""
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
            slot_w = min(_width(prev), _width(item)) * 0.52
            if abs(_x_center(item) - _x_center(prev)) <= slot_w:
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
    containment_threshold: float = 0.72,
    max_inner_area_ratio: float = 0.45,
) -> list[dict]:
    """
    Drop cap/tag fragments nested inside bottle bodies and merge same-brand overlaps.
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
            cap_fragment = _is_cap_fragment(inner, outer)
            if nested or cap_fragment:
                drop[inner_idx] = True

    survivors = [item for idx, item in enumerate(facings) if not drop[idx]]
    if len(survivors) <= 1:
        return survivors

    # Pass 2: drop unknown/low-conf cap bands sitting on a labeled neighbor column.
    drop = [False] * len(survivors)
    for inner_idx, inner in enumerate(survivors):
        if _brand_key(inner) not in {"", "unknown"}:
            continue
        for outer_idx, outer in enumerate(survivors):
            if inner_idx == outer_idx or drop[inner_idx]:
                continue
            if _brand_key(outer) in {"", "unknown"}:
                continue
            if not _same_row(inner, outer):
                continue
            if _is_cap_fragment(inner, outer) or (
                _horizontal_overlap_ratio(inner, outer) >= 0.4
                and _area(inner) < _area(outer) * 0.35
            ):
                drop[inner_idx] = True

    survivors = [item for idx, item in enumerate(survivors) if not drop[idx]]
    if len(survivors) <= 1:
        return survivors

    # Pass 3: merge overlapping facings with the same brand (cap + body both labeled).
    drop = [False] * len(survivors)
    for idx_a, a in enumerate(survivors):
        if drop[idx_a]:
            continue
        brand_a = _brand_key(a)
        if not brand_a or brand_a == "unknown":
            continue
        for idx_b in range(idx_a + 1, len(survivors)):
            if drop[idx_b]:
                continue
            b = survivors[idx_b]
            if _brand_key(b) != brand_a:
                continue
            if not _same_row(a, b):
                continue
            overlap = (
                _iou(a, b) >= 0.22
                or _containment_ratio(a, b) >= 0.55
                or _containment_ratio(b, a) >= 0.55
                or _is_cap_fragment(a, b)
                or _is_cap_fragment(b, a)
            )
            if not overlap:
                continue
            drop_idx = idx_a if _pick_preferred(a, b) == 0 else idx_b
            drop[drop_idx] = True

    survivors = [item for idx, item in enumerate(survivors) if not drop[idx]]

    # Pass 4: one facing per bottle column per row (helps dense multi-row shelves).
    return _deduplicate_row_slots(survivors)
