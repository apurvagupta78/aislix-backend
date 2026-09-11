"""
Shelf / bay audit scope — separate in-scope facings from adjacent categories and frame edges.

Out-of-scope facings must not reduce share-of-facings, OSA, or placement KPIs.
They may still appear as informational "adjacent category" findings.
"""

from __future__ import annotations

from typing import Any

# Fraction of image width/height treated as neighboring-bay margin when bboxes exist.
HORIZONTAL_MARGIN = 0.08
VERTICAL_MARGIN = 0.12

SCOPE_AUDITED = "audited_bay"
SCOPE_ADJACENT = "adjacent_bay"
SCOPE_BACKGROUND = "background"
SCOPE_UNKNOWN = "unknown"

_UNCLASSIFIED_BRANDS = {"", "unknown", "unidentified", "unclassified", "n/a"}


def _bbox_center(item: dict) -> tuple[float, float] | None:
    try:
        x1, y1, x2, y2 = int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"])
    except (KeyError, TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def facing_in_frame_margin(item: dict, image_shape: tuple[int, ...] | None) -> bool:
    """True when the facing centroid lies in the outer margin of the frame."""
    if not image_shape or len(image_shape) < 2:
        return False
    center = _bbox_center(item)
    if not center:
        return False
    h, w = int(image_shape[0]), int(image_shape[1])
    cx, cy = center
    return (
        cx < w * HORIZONTAL_MARGIN
        or cx > w * (1.0 - HORIZONTAL_MARGIN)
        or cy < h * VERTICAL_MARGIN
        or cy > h * (1.0 - VERTICAL_MARGIN)
    )


def annotate_audit_scope(
    classified: list[dict],
    *,
    image_shape: tuple[int, ...] | None,
    scan_context: dict | None,
) -> dict[str, Any]:
    """
    Tag each facing with audit_scope_zone and compute scope summary.

    Category mismatches in frame margins are treated as adjacent bay (not execution failures).
    """
    audited_sub = (scan_context or {}).get("sub_category") or ""
    in_scope = 0
    adjacent = 0
    background = 0
    has_bbox = any(_bbox_center(row) for row in classified)

    for item in classified:
        zone = SCOPE_AUDITED
        is_mismatch = item.get("subcategory_match") is False or item.get("compliance_issue")

        if is_mismatch and has_bbox and facing_in_frame_margin(item, image_shape):
            zone = SCOPE_ADJACENT
            item["placement_excluded_reason"] = "frame_edge_adjacent_category"
        elif is_mismatch:
            # In-bay category mismatch — counts toward placement KPIs.
            zone = SCOPE_AUDITED
            item["placement_excluded_reason"] = "category_mismatch"
        elif (item.get("brand") or "").strip().lower() in _UNCLASSIFIED_BRANDS:
            zone = SCOPE_UNKNOWN

        item["audit_scope_zone"] = zone
        if zone == SCOPE_AUDITED:
            in_scope += 1
        elif zone == SCOPE_ADJACENT:
            adjacent += 1
        else:
            background += 1

    return {
        "audited_sub_category": audited_sub or None,
        "in_scope_facings": in_scope,
        "adjacent_bay_facings": adjacent,
        "background_facings": background,
        "total_facings": len(classified),
        "has_bbox_scope": has_bbox,
        "state": "available" if classified else "insufficient_evidence",
    }


def scoped_misplaced_count(classified: list[dict]) -> int:
    """Placement violations — only in-scope category mismatches (excludes frame-edge neighbors)."""
    count = 0
    for item in classified:
        if item.get("audit_scope_zone") != SCOPE_AUDITED:
            continue
        if item.get("subcategory_match") is False or item.get("compliance_issue"):
            count += 1
    return count


def apply_audit_scope_after_compliance(
    classified: list[dict],
    inventory: list[dict],
    *,
    image_shape: tuple[int, ...] | None,
    scan_context: dict | None,
) -> tuple[list[dict], list[dict], int, dict[str, Any]]:
    """Tag scope zones, recompute scoped placement count, and filter inventory KPI rows."""
    summary = annotate_audit_scope(classified, image_shape=image_shape, scan_context=scan_context)
    misplaced = scoped_misplaced_count(classified)
    inventory = filter_inventory_to_audit_scope(inventory, classified)
    return classified, inventory, misplaced, summary


def adjacent_category_findings(classified: list[dict]) -> list[dict]:
    """Informational rows for facings excluded from placement KPIs (neighboring categories)."""
    findings: list[dict] = []
    for item in classified:
        if item.get("audit_scope_zone") != SCOPE_ADJACENT:
            continue
        findings.append(
            {
                "brand": item.get("brand"),
                "product_name": item.get("product_name"),
                "reason": item.get("placement_excluded_reason") or "category_mismatch",
                "zone": SCOPE_ADJACENT,
            }
        )
    return findings


def filter_inventory_to_audit_scope(inventory: list[dict], classified: list[dict]) -> list[dict]:
    """
    Mark inventory rows out of audit scope when all contributing facings are adjacent/background.
    Sets counted_in_totals=False for share/KPI denominators.
    """
    if not classified:
        return inventory

    mismatch_keys: set[tuple[str, str]] = set()
    in_scope_keys: set[tuple[str, str]] = set()
    for item in classified:
        key = (
            (item.get("brand") or "").strip().lower(),
            (item.get("product_name") or "").strip().lower(),
        )
        if item.get("audit_scope_zone") == SCOPE_AUDITED:
            in_scope_keys.add(key)
        elif item.get("subcategory_match") is False:
            mismatch_keys.add(key)

    out = []
    for row in inventory:
        row = dict(row)
        key = (
            (row.get("brand") or "").strip().lower(),
            (row.get("product_name") or row.get("product") or "").strip().lower(),
        )
        if key in mismatch_keys and key not in in_scope_keys:
            row["counted_in_totals"] = False
            row["audit_scope_zone"] = SCOPE_ADJACENT
            row["compliance_status"] = "category_mismatch"
        else:
            row.setdefault("counted_in_totals", True)
            row.setdefault("audit_scope_zone", SCOPE_AUDITED)
        out.append(row)
    return out
