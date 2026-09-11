"""
Merge multiple shelf photos into one audit — dedupe facings, preserve evidence per photo.
"""

from __future__ import annotations

from typing import Any


def _facing_key(row: dict) -> str:
    brand = (row.get("brand") or "").strip().lower()
    product = (row.get("product_name") or row.get("product") or "").strip().lower()
    variant = (row.get("variant") or "").strip().lower()
    sku = (row.get("sku") or "").strip().lower()
    if sku:
        return f"sku:{sku}"
    return "|".join(p for p in (brand, product, variant) if p)


def _bbox_iou(a: dict, b: dict) -> float:
    try:
        ax1, ay1, ax2, ay2 = int(a["x1"]), int(a["y1"]), int(a["x2"]), int(a["y2"])
        bx1, by1, bx2, by2 = int(b["x1"]), int(b["y1"]), int(b["x2"]), int(b["y2"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if ax2 <= ax1 or ay2 <= ay1 or bx2 <= bx1 or by2 <= by1:
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def merge_classified_photos(photo_batches: list[list[dict]], *, iou_threshold: float = 0.45) -> dict[str, Any]:
    """
    Merge classified facings from multiple photos of the same bay.

    Dedupes identical SKU/product keys; when bboxes overlap across photos, keeps higher confidence.
    """
    merged: list[dict] = []
    photo_counts: list[int] = []

    for photo_idx, batch in enumerate(photo_batches):
        added = 0
        for row in batch:
            item = dict(row)
            item["photo_index"] = photo_idx + 1
            item["photo_count_hint"] = len(photo_batches)
            key = _facing_key(item)
            duplicate_idx: int | None = None
            for i, existing in enumerate(merged):
                if _facing_key(existing) != key:
                    continue
                if _bbox_iou(item, existing) >= iou_threshold:
                    duplicate_idx = i
                    break
                if not _bbox_center_exists(item) or not _bbox_center_exists(existing):
                    duplicate_idx = i
                    break
            if duplicate_idx is not None:
                if float(item.get("confidence") or 0) > float(merged[duplicate_idx].get("confidence") or 0):
                    merged[duplicate_idx] = item
            else:
                merged.append(item)
                added += 1
        photo_counts.append(added)

    return {
        "classified": merged,
        "photo_count": len(photo_batches),
        "facings_per_photo": photo_counts,
        "merged_facings": len(merged),
        "state": "available" if merged else "insufficient_evidence",
    }


def _bbox_center_exists(row: dict) -> bool:
    try:
        x1, y1, x2, y2 = int(row["x1"]), int(row["y1"]), int(row["x2"]), int(row["y2"])
        return x2 > x1 and y2 > y1
    except (KeyError, TypeError, ValueError):
        return False


def extract_photo_batches_from_metadata(metadata: dict | None) -> list[list[dict]] | None:
    """Read additional photo classifications from scan metadata."""
    if not metadata:
        return None
    batches: list[list[dict]] = []
    primary = metadata.get("classified") or metadata.get("facings")
    if isinstance(primary, list) and primary:
        batches.append([dict(r) for r in primary if isinstance(r, dict)])
    extra = metadata.get("additional_photos") or metadata.get("multi_photo_classified")
    if isinstance(extra, list):
        for entry in extra:
            if isinstance(entry, list):
                batches.append([dict(r) for r in entry if isinstance(r, dict)])
            elif isinstance(entry, dict) and isinstance(entry.get("classified"), list):
                batches.append([dict(r) for r in entry["classified"] if isinstance(r, dict)])
    return batches if len(batches) > 1 else None
