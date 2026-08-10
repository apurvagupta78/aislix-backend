"""Filter duplicate/nested YOLO facings (e.g. bottle cap inside bottle body)."""

from __future__ import annotations


def _area(item: dict) -> float:
    return max(0.0, float(item["x2"]) - float(item["x1"])) * max(
        0.0, float(item["y2"]) - float(item["y1"])
    )


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


def _same_row(a: dict, b: dict) -> bool:
    ay1, ay2 = float(a["y1"]), float(a["y2"])
    by1, by2 = float(b["y1"]), float(b["y2"])
    if ay2 <= ay1 or by2 <= by1:
        return True
    acy = (ay1 + ay2) / 2.0
    bcy = (by1 + by2) / 2.0
    row_tol = max(ay2 - ay1, by2 - by1) * 0.55
    return abs(acy - bcy) <= row_tol


def filter_nested_facings(
    facings: list[dict],
    *,
    containment_threshold: float = 0.72,
    max_inner_area_ratio: float = 0.45,
) -> list[dict]:
    """
    Drop small facings nested inside larger neighbors (cap-only crops, tag fragments).
    Prefer keeping the larger facing; drop inner when Unknown or lower confidence.
    """
    if len(facings) <= 1:
        return facings

    drop = [False] * len(facings)
    for inner_idx, inner in enumerate(facings):
        inner_area = _area(inner)
        if inner_area <= 0:
            continue
        for outer_idx, outer in enumerate(facings):
            if inner_idx == outer_idx:
                continue
            outer_area = _area(outer)
            if outer_area <= inner_area:
                continue
            if inner_area / outer_area > max_inner_area_ratio:
                continue
            if not _same_row(inner, outer):
                continue
            if _containment_ratio(inner, outer) < containment_threshold:
                continue

            inner_brand = (inner.get("brand") or "").strip().lower()
            outer_brand = (outer.get("brand") or "").strip().lower()
            inner_conf = float(inner.get("confidence") or 0)
            outer_conf = float(outer.get("confidence") or 0)

            if inner_brand in {"", "unknown"}:
                drop[inner_idx] = True
                continue
            if outer_brand in {"", "unknown"}:
                continue
            if inner_conf <= outer_conf + 0.05:
                drop[inner_idx] = True

    return [item for idx, item in enumerate(facings) if not drop[idx]]
