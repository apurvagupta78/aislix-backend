"""Optional local YOLO detection overlays for Make.com scans (bounding boxes)."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from app.inventory import normalize_classified_labels


def make_local_annotate_enabled() -> bool:
    return os.getenv("MAKE_LOCAL_ANNOTATE", "true").lower() in {"1", "true", "yes"}


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


def _shelf_band_from_position(position: str) -> str:
    text = (position or "").lower()
    if any(token in text for token in ("top", "upper")):
        return "top"
    if any(token in text for token in ("bottom", "lower", "floor")):
        return "bottom"
    if any(token in text for token in ("middle", "mid", "center", "centre")):
        return "middle"
    return ""


def _assign_inventory_to_boxes(
    boxes: list[dict],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
) -> list[dict]:
    """Best-effort label assignment: row bands + left-to-right qty slots."""
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

    rows = _cluster_boxes_into_rows(boxes)
    inv_rows = _unique_inventory_for_assignment(inventory)
    inv_rows.sort(
        key=lambda row: _inventory_vertical_sort_key(row, planogram_items=planogram_items),
    )

    labeled: list[dict] = []
    inv_idx = 0
    for row_boxes in rows:
        if inv_idx >= len(inv_rows):
            inv = inv_rows[-1]
        else:
            inv = inv_rows[inv_idx]
            inv_idx += 1
        brand = inv.get("brand") or "Product"
        product_name = inv.get("product_name") or "Detected"
        variant = inv.get("variant") or ""
        confidence = float(inv.get("confidence") or 0.0)
        for box in row_boxes:
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


def _unique_inventory_for_assignment(inventory: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in inventory:
        key = (
            (row.get("brand") or "").strip().lower(),
            (row.get("product_name") or row.get("product") or "").strip().lower(),
            (row.get("variant") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique or list(inventory)


def _inventory_vertical_sort_key(
    row: dict,
    *,
    planogram_items: list[dict] | None = None,
) -> tuple[int, int, str]:
    band_order = {"top": 0, "upper": 0, "middle": 1, "mid": 1, "center": 1, "bottom": 2, "lower": 2, "floor": 2}
    position = (row.get("shelf_position") or row.get("location") or "").lower()
    band = 3
    for token, order in band_order.items():
        if token in position:
            band = order
            break
    plano_idx = 999
    if planogram_items:
        row_brand = (row.get("brand") or "").strip().lower()
        row_variant = (row.get("variant") or "").strip().lower()
        row_product = (row.get("product_name") or row.get("product") or "").strip().lower()
        for idx, item in enumerate(planogram_items):
            if (item.get("brand") or "").strip().lower() != row_brand:
                continue
            item_variant = (item.get("variant") or "").strip().lower()
            item_product = (item.get("product_name") or item.get("product") or "").strip().lower()
            if row_variant and item_variant and row_variant == item_variant:
                plano_idx = idx
                break
            if row_product and item_product and row_product == item_product:
                plano_idx = idx
                break
    return (band, plano_idx, (row.get("variant") or row.get("product_name") or ""))


def build_local_detection_facings(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
) -> list[dict]:
    from app.pipeline import _detect_boxes_for_scan

    boxes, _shelf_mode, _gap_stats = _detect_boxes_for_scan(image, metadata, scan_context)
    facings: list[dict] = []
    for x1, y1, x2, y2 in boxes:
        facings.append({"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)})
    assigned = _assign_inventory_to_boxes(facings, inventory, planogram_items=planogram_items)
    return normalize_classified_labels(assigned)
