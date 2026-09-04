"""Optional local YOLO detection overlays for Make.com scans (bounding boxes)."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from app.inventory import normalize_classified_labels


def make_local_annotate_enabled() -> bool:
    return os.getenv("MAKE_LOCAL_ANNOTATE", "true").lower() in {"1", "true", "yes"}


def make_use_openai_bbox_for_annotate() -> bool:
    return os.getenv("MAKE_USE_OPENAI_BBOX", "false").lower() in {"1", "true", "yes"}


def make_sku_band_annotate_enabled() -> bool:
    return os.getenv("MAKE_SKU_BAND_ANNOTATE", "true").lower() in {"1", "true", "yes"}


def make_per_box_annotate_enabled() -> bool:
    return os.getenv("MAKE_ANNOTATE_PER_BOX", "false").lower() in {"1", "true", "yes"}


def make_sku_band_use_gpt_layout() -> bool:
    """GPT bbox spans for SKU bands are often wrong — off by default."""
    return os.getenv("MAKE_SKU_BAND_USE_GPT_LAYOUT", "false").lower() in {"1", "true", "yes"}


def make_yolo_overlay_only() -> bool:
    """Draw local YOLO detection boxes on Make scans — no product text labels."""
    return os.getenv("MAKE_YOLO_OVERLAY_ONLY", "true").lower() in {"1", "true", "yes"}


def make_annotate_draw_labels() -> bool:
    if make_yolo_overlay_only():
        return os.getenv("MAKE_ANNOTATE_DRAW_LABELS", "false").lower() in {"1", "true", "yes"}
    return os.getenv("MAKE_ANNOTATE_DRAW_LABELS", "true").lower() in {"1", "true", "yes"}


def make_planogram_yolo_qty_enabled() -> bool:
    """Use YOLO per-row facing counts for planogram inventory qty when GPT under-counts rows."""
    return os.getenv("MAKE_PLANOGRAM_YOLO_QTY", "true").lower() in {"1", "true", "yes"}


def _annotate_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _default_product_zone(img_h: int, img_w: int) -> tuple[int, int, int, int]:
    return (
        int(img_w * 0.04),
        int(img_h * _annotate_env_float("MAKE_ANNOTATE_ZONE_TOP_RATIO", 0.12)),
        int(img_w * 0.96),
        int(img_h * _annotate_env_float("MAKE_ANNOTATE_ZONE_BOTTOM_RATIO", 0.96)),
    )


def _inventory_sku_key(row: dict) -> tuple[str, str, str]:
    return (
        (row.get("brand") or "").strip().lower(),
        (row.get("product_name") or row.get("product") or "").strip().lower(),
        (row.get("variant") or "").strip().lower(),
    )


def _variants_match(row_variant: str, item_variant: str) -> bool:
    rv = (row_variant or "").strip().lower()
    iv = (item_variant or "").strip().lower()
    if not rv or not iv:
        return True
    if rv == iv:
        return True
    if rv in iv or iv in rv:
        return True
    ta = set(rv.replace("-", " ").replace("&", " and ").split())
    tb = set(iv.replace("-", " ").replace("&", " and ").split())
    if not ta or not tb:
        return False
    return len(ta & tb) / max(len(ta), len(tb)) >= 0.5


def _inventory_matches_planogram(row: dict, item: dict) -> bool:
    row_brand = (row.get("brand") or "").strip().lower()
    item_brand = (item.get("brand") or "").strip().lower()
    if row_brand != item_brand:
        return False
    row_variant = (row.get("variant") or "").strip()
    item_variant = (item.get("variant") or "").strip()
    if row_variant and item_variant:
        return _variants_match(row_variant, item_variant)
    row_product = (row.get("product_name") or row.get("product") or "").strip().lower()
    item_product = (item.get("product_name") or item.get("product") or "").strip().lower()
    return bool(row_product and item_product and row_product == item_product)


def _unique_inventory_for_assignment(inventory: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in inventory:
        if row.get("counted_in_totals") is False:
            continue
        key = _inventory_sku_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique or list(inventory)


def _inventory_key_from_product_row(row: dict) -> tuple[str, str, str]:
    return (
        (row.get("brand") or "").strip().lower(),
        (row.get("product_name") or row.get("product") or "").strip().lower(),
        (row.get("variant") or "").strip().lower(),
    )


def _inventory_in_visual_order(
    inventory: list[dict],
    product_rows: list[dict] | None,
) -> list[dict]:
    """Preserve GPT products[] order — typically top-to-bottom shelf scan order."""
    unique = _unique_inventory_for_assignment(inventory)
    if not product_rows:
        return unique

    inv_by_key = {_inventory_sku_key(row): row for row in unique}
    ordered: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for prow in product_rows:
        key = _inventory_key_from_product_row(prow)
        if not key[0] and not key[1]:
            continue
        inv = inv_by_key.get(key)
        if inv is None:
            inv = inv_by_key.get(_inventory_sku_key(prow))
        if inv is None or key in seen:
            continue
        ordered.append(inv)
        seen.add(_inventory_sku_key(inv))
    for row in unique:
        key = _inventory_sku_key(row)
        if key not in seen:
            ordered.append(row)
    return ordered or unique


def _inventory_in_planogram_order(
    inventory: list[dict],
    planogram_items: list[dict] | None,
    *,
    product_rows: list[dict] | None = None,
) -> list[dict]:
    unique = _unique_inventory_for_assignment(inventory)
    if not planogram_items:
        return _inventory_in_visual_order(inventory, product_rows)

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
                return max(1, int(item.get("expected_qty") or 0))
    return max(1, int(row.get("quantity") or row.get("facings") or 1))


def _proportional_band_heights(zone_h: int, weights: list[int]) -> list[int]:
    n = len(weights)
    if n <= 0 or zone_h <= 0:
        return []
    if n == 1:
        return [zone_h]

    total = sum(max(1, w) for w in weights)
    heights: list[int] = []
    assigned = 0
    for i, weight in enumerate(weights):
        if i == n - 1:
            heights.append(max(1, zone_h - assigned))
            continue
        remaining = zone_h - assigned
        remaining_skus = n - i
        share = max(1, round(remaining * max(1, weight) / total))
        share = min(share, max(1, remaining - (remaining_skus - 1)))
        heights.append(share)
        assigned += share
    return heights


def _facing_to_zone(facing: dict[str, Any]) -> tuple[int, int, int, int]:
    return int(facing["x1"]), int(facing["y1"]), int(facing["x2"]), int(facing["y2"])


def _band_layout_from_openai_facings(
    inv_rows: list[dict],
    openai_facings: list[dict],
    image_shape: tuple[int, ...],
) -> list[tuple[int, int, int, int]] | None:
    """Use GPT bbox vertical spans only when trusted and one box per inventory SKU."""
    if not make_sku_band_use_gpt_layout():
        return None
    if len(openai_facings) != len(inv_rows):
        return None

    from app.make_scan import openai_bbox_facings_trusted

    if not openai_bbox_facings_trusted(openai_facings, inv_rows, image_shape):
        return None

    keyed: dict[tuple[str, str, str], dict] = {}
    for facing in openai_facings:
        key = _inventory_sku_key(facing)
        if key not in keyed:
            keyed[key] = facing

    paired: list[tuple[dict, tuple[int, int, int, int]]] = []
    for row in inv_rows:
        facing = keyed.get(_inventory_sku_key(row))
        if not facing:
            return None
        paired.append((row, _facing_to_zone(facing)))

    paired.sort(key=lambda item: (item[1][1] + item[1][3]) / 2.0)
    return [zone for _row, zone in paired]


def _row_bounds_from_clusters(rows: list[list[dict]]) -> list[dict]:
    bounds: list[dict] = []
    for row in rows:
        if not row:
            continue
        bounds.append(
            {
                "x1": min(int(b["x1"]) for b in row),
                "y1": min(int(b["y1"]) for b in row),
                "x2": max(int(b["x2"]) for b in row),
                "y2": max(int(b["y2"]) for b in row),
            }
        )
    return bounds


def _shelf_row_bounds_from_image(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
) -> list[dict]:
    """Detect physical shelf rows via local YOLO — used only for band placement, not labels."""
    if not make_local_annotate_enabled():
        return []
    img_h = int(image.shape[0])
    try:
        boxes = _detect_product_boxes(image, metadata, scan_context)
    except Exception:
        return []
    boxes = _filter_product_zone_boxes(boxes, img_h)
    if len(boxes) < 2:
        return []
    rows = _cluster_boxes_into_rows(boxes)
    bounds = _row_bounds_from_clusters(rows)
    return bounds if len(bounds) >= 2 else []


def _vertical_overlap_ratio(row_y1: int, row_y2: int, box_y1: int, box_y2: int) -> float:
    inter = max(0, min(row_y2, box_y2) - max(row_y1, box_y1))
    if inter <= 0:
        return 0.0
    row_h = max(row_y2 - row_y1, 1)
    box_h = max(box_y2 - box_y1, 1)
    return inter / min(row_h, box_h)


def _usable_gpt_bbox_facings(
    product_rows: list[dict],
    image_shape: tuple[int, ...],
) -> list[dict]:
    from app.make_scan import build_facings_from_make_products

    img_h = int(image_shape[0])
    max_height = _annotate_env_float("MAKE_ANNOTATE_GPT_BBOX_MAX_HEIGHT_RATIO", 0.38)
    facings = build_facings_from_make_products(product_rows, image_shape)
    usable: list[dict] = []
    for facing in facings:
        height_ratio = (int(facing["y2"]) - int(facing["y1"])) / max(img_h, 1)
        if height_ratio > max_height:
            continue
        usable.append(facing)
    return usable


def _inv_from_facing(facing: dict, inventory: list[dict]) -> dict:
    inv_by_key = {_inventory_sku_key(row): row for row in _unique_inventory_for_assignment(inventory)}
    return inv_by_key.get(_inventory_sku_key(facing), facing)


def _make_band_facing(
    inv: dict,
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    recognition_source: str,
) -> dict:
    qty = int(inv.get("quantity") or inv.get("facings") or 0)
    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": max(y1 + 1, y2),
        "brand": inv.get("brand") or "Product",
        "product_name": inv.get("product_name") or inv.get("product") or "Detected",
        "variant": inv.get("variant") or "",
        "confidence": float(inv.get("confidence") or 0.0),
        "annotation_qty": qty,
        "pack_text": " ".join(
            filter(
                None,
                [inv.get("brand"), inv.get("product_name") or inv.get("product"), inv.get("variant")],
            )
        ).strip(),
        "recognition_source": recognition_source,
    }


def _assign_rows_by_gpt_bbox_overlap(
    row_bounds: list[dict],
    product_rows: list[dict],
    inventory: list[dict],
    image_shape: tuple[int, ...],
) -> list[tuple[dict, dict]]:
    gpt_facings = _usable_gpt_bbox_facings(product_rows, image_shape)
    visual_order = _inventory_in_visual_order(inventory, product_rows)
    assignments: list[tuple[dict, dict]] = []

    for idx, row in enumerate(row_bounds):
        ry1, ry2 = int(row["y1"]), int(row["y2"])
        row_cy = (ry1 + ry2) / 2.0
        containing = [
            facing
            for facing in gpt_facings
            if int(facing["y1"]) <= row_cy <= int(facing["y2"])
        ]
        if containing:
            best_facing = max(
                containing,
                key=lambda facing: _vertical_overlap_ratio(
                    ry1, ry2, int(facing["y1"]), int(facing["y2"])
                ),
            )
            assignments.append((row, _inv_from_facing(best_facing, inventory)))
            continue

        overlapping = [
            (
                facing,
                _vertical_overlap_ratio(ry1, ry2, int(facing["y1"]), int(facing["y2"])),
            )
            for facing in gpt_facings
        ]
        overlapping = [(f, score) for f, score in overlapping if score >= 0.15]
        if overlapping:
            best_facing = min(
                overlapping,
                key=lambda item: abs(
                    row_cy - (int(item[0]["y1"]) + int(item[0]["y2"])) / 2.0
                ),
            )[0]
            assignments.append((row, _inv_from_facing(best_facing, inventory)))
            continue
        nearest: dict | None = None
        nearest_dist = float("inf")
        for facing in gpt_facings:
            fcy = (int(facing["y1"]) + int(facing["y2"])) / 2.0
            dist = abs(row_cy - fcy)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = facing
        if nearest is not None:
            assignments.append((row, _inv_from_facing(nearest, inventory)))
            continue
        if idx < len(visual_order):
            assignments.append((row, visual_order[idx]))
    return assignments


def _merge_row_assignments(
    assignments: list[tuple[dict, dict]],
) -> list[tuple[list[dict], dict]]:
    if not assignments:
        return []
    merged: list[tuple[list[dict], dict]] = []
    current_rows = [assignments[0][0]]
    current_inv = assignments[0][1]
    current_key = _inventory_sku_key(current_inv)
    for row, inv in assignments[1:]:
        if _inventory_sku_key(inv) == current_key:
            current_rows.append(row)
            continue
        merged.append((current_rows, current_inv))
        current_rows = [row]
        current_inv = inv
        current_key = _inventory_sku_key(inv)
    merged.append((current_rows, current_inv))
    return merged


def _bands_from_row_assignments(
    assignments: list[tuple[list[dict], dict]],
    *,
    img_w: int,
    recognition_source: str,
) -> list[dict]:
    bands: list[dict] = []
    pad = max(2, int(img_w * 0.01))
    for rows, inv in assignments:
        if not rows:
            continue
        x1 = max(0, min(b["x1"] for b in rows) - pad)
        x2 = min(img_w - 1, max(b["x2"] for b in rows) + pad)
        y1 = min(b["y1"] for b in rows)
        y2 = max(b["y2"] for b in rows)
        bands.append(
            _make_band_facing(
                inv,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                recognition_source=recognition_source,
            )
        )
    return bands


def _bands_from_shelf_rows_with_gpt_labels(
    row_bounds: list[dict],
    inventory: list[dict],
    product_rows: list[dict],
    image_shape: tuple[int, ...],
    *,
    img_w: int,
    planogram_items: list[dict] | None,
) -> list[dict]:
    """Label each detected shelf row from GPT bbox overlap; merge rows per SKU when planogram."""
    assignments = _assign_rows_by_gpt_bbox_overlap(row_bounds, product_rows, inventory, image_shape)
    if not assignments:
        return []

    if planogram_items:
        merged = _merge_row_assignments(assignments)
        return _bands_from_row_assignments(
            merged,
            img_w=img_w,
            recognition_source="make.com+shelf_row_gpt",
        )

    return _bands_from_row_assignments(
        [( [row], inv) for row, inv in assignments],
        img_w=img_w,
        recognition_source="make.com+shelf_row_gpt",
    )


def _bands_from_shelf_rows(
    inv_rows: list[dict],
    row_bounds: list[dict],
    weights: list[int],
    *,
    img_w: int,
) -> list[dict]:
    """Merge detected shelf rows into one band per inventory SKU (planogram-weighted)."""
    n_rows = len(row_bounds)
    if n_rows <= 0 or not inv_rows:
        return []

    row_counts = _proportional_row_counts(n_rows, weights)
    bands: list[dict] = []
    row_idx = 0
    for inv, count in zip(inv_rows, row_counts):
        if count <= 0:
            continue
        group = row_bounds[row_idx : row_idx + count]
        if not group:
            break
        pad = max(2, int(img_w * 0.01))
        x1 = max(0, min(b["x1"] for b in group) - pad)
        x2 = min(img_w - 1, max(b["x2"] for b in group) + pad)
        y1 = min(b["y1"] for b in group)
        y2 = max(b["y2"] for b in group)
        qty = int(inv.get("quantity") or inv.get("facings") or 0)
        bands.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": max(y1 + 1, y2),
                "brand": inv.get("brand") or "Product",
                "product_name": inv.get("product_name") or inv.get("product") or "Detected",
                "variant": inv.get("variant") or "",
                "confidence": float(inv.get("confidence") or 0.0),
                "annotation_qty": qty,
                "pack_text": " ".join(
                    filter(
                        None,
                        [inv.get("brand"), inv.get("product_name") or inv.get("product"), inv.get("variant")],
                    )
                ).strip(),
                "recognition_source": "make.com+shelf_row_band",
            }
        )
        row_idx += count
    return bands


def build_sku_band_facings(
    image: np.ndarray,
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
    openai_facings: list[dict] | None = None,
    product_rows: list[dict] | None = None,
    metadata: dict[str, Any] | None = None,
    scan_context: dict[str, Any] | None = None,
) -> list[dict]:
    """One horizontal band per inventory SKU — labels/qty come from GPT inventory directly."""
    img_h, img_w = int(image.shape[0]), int(image.shape[1])
    default_zone = _default_product_zone(img_h, img_w)
    x1, y1, x2, y2 = default_zone

    plano_rows = planogram_items
    if planogram_items:
        from app.planogram_compliance import _aggregate_planogram_by_product

        plano_rows = _aggregate_planogram_by_product(planogram_items)

    inv_rows = _inventory_in_planogram_order(inventory, plano_rows, product_rows=product_rows)
    if not inv_rows:
        return []

    weights = [_weight_for_inventory_row(row, plano_rows, idx=i) for i, row in enumerate(inv_rows)]

    if metadata is not None and scan_context is not None:
        row_bounds = _shelf_row_bounds_from_image(image, metadata, scan_context)
        if row_bounds:
            if product_rows:
                row_bands = _bands_from_shelf_rows_with_gpt_labels(
                    row_bounds,
                    inventory,
                    product_rows,
                    image.shape,
                    img_w=img_w,
                    planogram_items=plano_rows,
                )
                if row_bands:
                    return normalize_classified_labels(row_bands)
            row_bands = _bands_from_shelf_rows(inv_rows, row_bounds, weights, img_w=img_w)
            if row_bands:
                return normalize_classified_labels(row_bands)

    layouts = _band_layout_from_openai_facings(inv_rows, openai_facings or [], image.shape)

    bands: list[dict] = []
    if layouts and len(layouts) == len(inv_rows):
        layout_rows = sorted(
            zip(inv_rows, layouts),
            key=lambda item: (item[1][1] + item[1][3]) / 2.0,
        )
        for inv, (bx1, by1, bx2, by2) in layout_rows:
            qty = int(inv.get("quantity") or inv.get("facings") or 0)
            bands.append(
                {
                    "x1": max(x1, bx1),
                    "y1": by1,
                    "x2": min(x2, bx2),
                    "y2": by2,
                    "brand": inv.get("brand") or "Product",
                    "product_name": inv.get("product_name") or inv.get("product") or "Detected",
                    "variant": inv.get("variant") or "",
                    "confidence": float(inv.get("confidence") or 0.0),
                    "annotation_qty": qty,
                    "pack_text": " ".join(
                        filter(
                            None,
                            [inv.get("brand"), inv.get("product_name") or inv.get("product"), inv.get("variant")],
                        )
                    ).strip(),
                    "recognition_source": "make.com+sku_band",
                }
            )
        return normalize_classified_labels(bands)

    zone_h = max(y2 - y1, 1)
    heights = _proportional_band_heights(zone_h, weights)
    y_cursor = y1
    for idx, inv in enumerate(inv_rows):
        band_h = heights[idx] if idx < len(heights) else max(1, y2 - y_cursor)
        band_y2 = y2 if idx == len(inv_rows) - 1 else min(y2, y_cursor + band_h)
        qty = int(inv.get("quantity") or inv.get("facings") or 0)
        bands.append(
            {
                "x1": x1,
                "y1": y_cursor,
                "x2": x2,
                "y2": max(y_cursor + 1, band_y2),
                "brand": inv.get("brand") or "Product",
                "product_name": inv.get("product_name") or inv.get("product") or "Detected",
                "variant": inv.get("variant") or "",
                "confidence": float(inv.get("confidence") or 0.0),
                "annotation_qty": qty,
                "pack_text": " ".join(
                    filter(
                        None,
                        [inv.get("brand"), inv.get("product_name") or inv.get("product"), inv.get("variant")],
                    )
                ).strip(),
                "recognition_source": "make.com+sku_band",
            }
        )
        y_cursor = band_y2

    return normalize_classified_labels(bands)


def build_yolo_overlay_facings(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
) -> list[dict]:
    """Local YOLO product boxes for display only — inventory/qty stay on Make/GPT."""
    if not make_local_annotate_enabled():
        return []
    img_h = int(image.shape[0])
    try:
        boxes = _detect_product_boxes(image, metadata, scan_context)
    except Exception:
        return []
    boxes = _filter_product_zone_boxes(boxes, img_h)
    if not boxes:
        return []
    return [
        {
            "x1": int(box["x1"]),
            "y1": int(box["y1"]),
            "x2": int(box["x2"]),
            "y2": int(box["y2"]),
            "brand": "",
            "product_name": "",
            "variant": "",
            "confidence": 0.0,
            "recognition_source": "make.com+yolo_overlay",
        }
        for box in boxes
    ]


def build_make_annotated_facings(
    image: np.ndarray,
    inventory: list[dict],
    *,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
    planogram_items: list[dict] | None = None,
    openai_facings: list[dict] | None = None,
    product_rows: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """Build facings used ONLY for annotated image rendering."""
    if make_yolo_overlay_only() and make_local_annotate_enabled():
        try:
            overlay = build_yolo_overlay_facings(image, metadata, scan_context)
            if overlay:
                return overlay, "make.com+yolo_overlay"
        except Exception as exc:
            print(f"Make YOLO overlay skipped: {exc}")

    unique_skus = len(_unique_inventory_for_assignment(inventory))
    max_sku_bands = int(os.getenv("MAKE_SKU_BAND_MAX", "30"))

    if make_sku_band_annotate_enabled() and 1 <= unique_skus <= max_sku_bands:
        gpt_layout_facings = openai_facings if make_sku_band_use_gpt_layout() else None
        bands = build_sku_band_facings(
            image,
            inventory,
            planogram_items=planogram_items,
            openai_facings=gpt_layout_facings,
            product_rows=product_rows,
            metadata=metadata,
            scan_context=scan_context,
        )
        if bands:
            src = bands[0].get("recognition_source") or ""
            if "shelf_row_gpt" in src:
                mode = "make.com+shelf_row_gpt"
            elif "shelf_row_band" in src:
                mode = "make.com+shelf_row_band"
            elif planogram_items:
                mode = "make.com+planogram_band"
            else:
                mode = "make.com+sku_band"
            return bands, mode

    if (
        openai_facings
        and make_use_openai_bbox_for_annotate()
        and len(openai_facings) >= unique_skus
    ):
        from app.make_scan import openai_bbox_facings_trusted, relabel_facings_by_vertical_order

        if openai_bbox_facings_trusted(openai_facings, inventory, image.shape):
            relabeled = relabel_facings_by_vertical_order(
                openai_facings,
                inventory,
                planogram_items=planogram_items,
            )
            return normalize_classified_labels(relabeled), "make.com+openai_bbox"

    if make_per_box_annotate_enabled() and make_local_annotate_enabled():
        try:
            local = build_local_detection_facings(
                image,
                metadata,
                scan_context,
                inventory,
                planogram_items=planogram_items,
            )
            if local:
                return local, "make.com+local_yolo"
        except Exception as exc:
            print(f"Make local annotate skipped: {exc}")

    bands = build_sku_band_facings(
        image,
        inventory,
        planogram_items=planogram_items,
        product_rows=product_rows,
        metadata=metadata,
        scan_context=scan_context,
    )
    if bands:
        return bands, "make.com+sku_band"
    return [], "make.com"


# --- Legacy per-box YOLO path (opt-in via MAKE_ANNOTATE_PER_BOX=true) ---


def _filter_product_zone_boxes(boxes: list[dict], img_h: int) -> list[dict]:
    min_y1 = _annotate_env_float("MAKE_ANNOTATE_MIN_Y1_RATIO", 0.15)
    min_center_y = _annotate_env_float("MAKE_ANNOTATE_MIN_CENTER_Y_RATIO", 0.17)
    max_height_ratio = _annotate_env_float("MAKE_ANNOTATE_MAX_BOX_HEIGHT_RATIO", 0.35)
    kept: list[dict] = []
    for box in boxes:
        y1 = int(box["y1"])
        y2 = int(box["y2"])
        if y2 <= y1:
            continue
        cy = (y1 + y2) / 2.0
        height_ratio = (y2 - y1) / max(img_h, 1)
        if y1 < img_h * min_y1 or cy < img_h * min_center_y:
            continue
        if height_ratio > max_height_ratio:
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


def _proportional_row_counts(n_rows: int, weights: list[int]) -> list[int]:
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
        share = min(share, max(1, remaining_rows - (remaining_skus - 1)))
        counts.append(share)
        assigned += share
    return counts


def _label_boxes_with_inventory(boxes: list[dict], inv: dict) -> list[dict]:
    brand = inv.get("brand") or "Product"
    product_name = inv.get("product_name") or inv.get("product") or "Detected"
    variant = inv.get("variant") or ""
    confidence = float(inv.get("confidence") or 0.0)
    return [
        {
            **box,
            "brand": brand,
            "product_name": product_name,
            "variant": variant,
            "confidence": confidence,
            "pack_text": f"{brand} {product_name} {variant}".strip(),
            "recognition_source": "make.com+local_detect",
        }
        for box in boxes
    ]


def _assign_inventory_to_boxes(
    boxes: list[dict],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
    img_h: int | None = None,
) -> list[dict]:
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


def _detect_product_boxes(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
) -> list[dict]:
    from app.pipeline import _detect_boxes_for_scan

    boxes, _shelf_mode, _gap_stats = _detect_boxes_for_scan(image, metadata, scan_context)
    return [{"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)} for x1, y1, x2, y2 in boxes]


def build_local_detection_facings(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
    inventory: list[dict],
    *,
    planogram_items: list[dict] | None = None,
) -> list[dict]:
    img_h = int(image.shape[0])
    facings = _detect_product_boxes(image, metadata, scan_context)
    assigned = _assign_inventory_to_boxes(
        facings,
        inventory,
        planogram_items=planogram_items,
        img_h=img_h,
    )
    return normalize_classified_labels(assigned)


# Backward-compatible alias
build_planogram_sku_band_facings = build_sku_band_facings


def _yolo_row_facing_counts(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
) -> list[int]:
    """Count YOLO detections per physical shelf row, top to bottom."""
    if not make_local_annotate_enabled():
        return []
    img_h = int(image.shape[0])
    try:
        boxes = _detect_product_boxes(image, metadata, scan_context)
    except Exception:
        return []
    boxes = _filter_product_zone_boxes(boxes, img_h)
    if not boxes:
        return []
    rows = _cluster_boxes_into_rows(boxes)
    return [len(row) for row in rows]


def apply_planogram_yolo_qty(
    image: np.ndarray,
    metadata: dict[str, Any],
    scan_context: dict[str, Any],
    inventory: list[dict],
    planogram_items: list[dict],
) -> tuple[list[dict], bool]:
    """
    Override inventory qty from YOLO row facing counts grouped by planogram weights.
    GPT keeps brand/variant identification; qty comes from counted boxes per shelf row.
    """
    if not make_planogram_yolo_qty_enabled() or not planogram_items:
        return inventory, False

    from app.planogram_compliance import _aggregate_planogram_by_product

    plano_rows = _aggregate_planogram_by_product(planogram_items)
    if len(plano_rows) < 2:
        return inventory, False

    per_row_counts = _yolo_row_facing_counts(image, metadata, scan_context)
    n_rows = len(per_row_counts)
    if n_rows < len(plano_rows):
        return inventory, False

    weights = [max(1, int(p.get("expected_qty") or 1)) for p in plano_rows]
    sku_row_spans = _proportional_row_counts(n_rows, weights)

    row_idx = 0
    plano_yolo_qty: list[tuple[dict, int]] = []
    for plano, span in zip(plano_rows, sku_row_spans):
        if span <= 0:
            plano_yolo_qty.append((plano, 0))
            continue
        qty = sum(per_row_counts[row_idx : row_idx + span])
        plano_yolo_qty.append((plano, qty))
        row_idx += span

    updated: list[dict] = []
    changed = False
    for item in inventory:
        row = dict(item)
        for plano, yolo_qty in plano_yolo_qty:
            if yolo_qty <= 0:
                continue
            if _inventory_matches_planogram(row, plano):
                prev = int(row.get("quantity") or row.get("facings") or 0)
                if prev != yolo_qty:
                    changed = True
                row["quantity"] = yolo_qty
                row["facings"] = yolo_qty
                row["qty_source"] = "yolo_row_count"
                row["stock_status"] = "in_stock" if yolo_qty > 2 else "low_stock"
                break
        updated.append(row)
    return updated, changed
