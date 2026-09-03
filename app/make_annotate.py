"""Optional local YOLO detection overlays for Make.com scans (bounding boxes)."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from app.inventory import normalize_classified_labels


def make_local_annotate_enabled() -> bool:
    return os.getenv("MAKE_LOCAL_ANNOTATE", "true").lower() in {"1", "true", "yes"}


def _annotate_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _filter_product_zone_boxes(boxes: list[dict], img_h: int) -> list[dict]:
    """Drop detections in ceiling/header zone before labeling."""
    min_y1 = _annotate_env_float("MAKE_ANNOTATE_MIN_Y1_RATIO", 0.12)
    min_center_y = _annotate_env_float("MAKE_ANNOTATE_MIN_CENTER_Y_RATIO", 0.14)
    kept: list[dict] = []
    for box in boxes:
        y1 = int(box["y1"])
        y2 = int(box["y2"])
        if y2 <= y1:
            continue
        cy = (y1 + y2) / 2.0
        if y1 < img_h * min_y1 or cy < img_h * min_center_y:
            continue
        kept.append(box)
    return kept


def _cluster_boxes_into_rows(boxes: list[dict], *, row_tolerance: float = 0.08) -> list[list[dict]]:
    if not boxes:
        return []
    heights = [max(1, int(b["y2"]) - int(b["y1"])) for b in boxes]
    median_h = sorted(heights)[len(heights) // 2]
    tol = max(median_h * 0.45, int(boxes[0]["y2"]) * row_tolerance)

    sorted_boxes = sorted(boxes, key=lambda b: (int(b["y1"]) + int(b["y2"])) / 2.0)
    rows: list[list[dict]] = []
    for box in sorted_boxes:
        cy = (int(box["y1"]) + int(box["y2"])) / 2.0
        placed = False
        for row in rows:
            row_cy = sum((int(b["y1"]) + int(b["y2"])) / 2.0 for b in row) / len(row)
            if abs(cy - row_cy) <= tol:
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    for row in rows:
        row.sort(key=lambda b: int(b["x1"]))
    rows.sort(key=lambda row: sum((int(b["y1"]) + int(b["y2"])) / 2.0 for b in row) / len(row))
    return rows


def _inventory_sku_key(row: dict) -> tuple[str, str, str]:
    return (
        (row.get("brand") or "").strip().lower(),
        (row.get("product_name") or row.get("product") or "").strip().lower(),
        (row.get("variant") or "").strip().lower(),
    )


def _planogram_item_key(item: dict) -> tuple[str, str, str]:
    return (
        (item.get("brand") or "").strip().lower(),
        (item.get("product_name") or item.get("product") or "").strip().lower(),
        (item.get("variant") or "").strip().lower(),
    )


def _inventory_matches_planogram(row: dict, item: dict) -> bool:
    row_brand = (row.get("brand") or "").strip().lower()
    item_brand = (item.get("brand") or "").strip().lower()
    if row_brand != item_brand:
        return False
    row_variant = (row.get("variant") or "").strip().lower()
    item_variant = (item.get("variant") or "").strip().lower()
    if row_variant and item_variant:
        return row_variant == item_variant
    row_product = (row.get("product_name") or row.get("product") or "").strip().lower()
    item_product = (item.get("product_name") or item.get("product") or "").strip().lower()
    return bool(row_product and item_product and row_product == item_product)


def _unique_inventory_for_assignment(inventory: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in inventory:
        key = _inventory_sku_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique or list(inventory)


def _inventory_in_planogram_order(
    inventory: list[dict],
    planogram_items: list[dict] | None,
) -> list[dict]:
    unique = _unique_inventory_for_assignment(inventory)
    if not planogram_items:
        return unique

    ordered: list[dict] = []
    used: set[tuple[str, str, str]] = set()
    for item in planogram_items:
        for row in unique:
            key = _inventory_sku_key(row)
            if key in used:
                continue
            if _inventory_matches_planogram(row, item):
                ordered.append(row)
                used.add(key)
                break
    for row in unique:
        key = _inventory_sku_key(row)
        if key not in used:
            ordered.append(row)
    return ordered


def _weight_for_inventory_row(
    row: dict,
    planogram_items: list[dict] | None,
    *,
    idx: int,
) -> int:
    if planogram_items:
        for item in planogram_items:
            if _inventory_matches_planogram(row, item):
                return max(1, int(item.get("expected_qty") or 1))
    return max(1, int(row.get("quantity") or row.get("facings") or 1))


def _proportional_row_counts(n_rows: int, weights: list[int]) -> list[int]:
    """Split shelf row clusters across SKUs (e.g. 6 chip rows → 3+1+2 by planogram qty)."""
    n_skus = len(weights)
    if n_rows <= 0 or n_skus <= 0:
        return []
    if n_rows <= n_skus:
        counts = [0] * n_skus
        for i in range(n_rows):
            counts[i] += 1
        return counts

    total = sum(max(1, w) for w in weights)
    counts: list[int] = []
    assigned = 0
    for i, weight in enumerate(weights):
        if i == n_skus - 1:
            counts.append(n_rows - assigned)
            continue
        remaining_rows = n_rows - assigned
        remaining_skus = n_skus - i
        share = max(1, round(remaining_rows * max(1, weight) / total))
        share = min(share, remaining_rows - (remaining_skus - 1))
        counts.append(share)
        assigned += share
    return counts


def _label_boxes_with_inventory(boxes: list[dict], inv: dict) -> list[dict]:
    brand = inv.get("brand") or "Product"
    product_name = inv.get("product_name") or inv.get("product") or "Detected"
    variant = inv.get("variant") or ""
    confidence = float(inv.get("confidence") or 0.0)
    labeled: list[dict] = []
    for box in boxes:
        labeled.append(
            {
                **box,
                "brand": brand,
                "product_name": product_name,
                "variant": variant,
                "confidence": confidence,
                "pack_text": f"{brand} {product_name} {variant}".strip(),
                "recognition_source": "make.com+local_detect",
            }
        )
    return labeled


def _assign_inventory_to_boxes(
    boxes: list[dict],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
    img_h: int | None = None,
) -> list[dict]:
    """Assign GPT inventory labels to YOLO boxes using shelf-row bands."""
    if not boxes:
        return []
    if not inventory:
        return [
            {
                **box,
                "brand": "Product",
                "product_name": "Detected",
                "variant": "",
                "confidence": 0.0,
                "recognition_source": "make.com+local_detect",
            }
            for box in boxes
        ]

    if img_h is not None:
        boxes = _filter_product_zone_boxes(boxes, img_h)
        if not boxes:
            return []

    rows = _cluster_boxes_into_rows(boxes)
    inv_rows = _inventory_in_planogram_order(inventory, planogram_items)
    n_rows = len(rows)
    n_skus = len(inv_rows)

    if n_skus == 0:
        return []

    labeled: list[dict] = []
    if n_rows > n_skus:
        weights = [_weight_for_inventory_row(row, planogram_items, idx=i) for i, row in enumerate(inv_rows)]
        row_counts = _proportional_row_counts(n_rows, weights)
        row_idx = 0
        for sku_idx, count in enumerate(row_counts):
            inv = inv_rows[sku_idx]
            for _ in range(count):
                if row_idx >= n_rows:
                    break
                labeled.extend(_label_boxes_with_inventory(rows[row_idx], inv))
                row_idx += 1
        return labeled

    for row_idx, row_boxes in enumerate(rows):
        inv = inv_rows[min(row_idx, n_skus - 1)]
        labeled.extend(_label_boxes_with_inventory(row_boxes, inv))
    return labeled


def build_local_detection_facings(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
) -> list[dict]:
    from app.pipeline import _detect_boxes_for_scan

    img_h = int(image.shape[0])
    boxes, _shelf_mode, _gap_stats = _detect_boxes_for_scan(image, metadata, scan_context)
    facings: list[dict] = []
    for x1, y1, x2, y2 in boxes:
        facings.append({"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)})
    assigned = _assign_inventory_to_boxes(
        facings,
        inventory,
        planogram_items=planogram_items,
        img_h=img_h,
    )
    return normalize_classified_labels(assigned)
