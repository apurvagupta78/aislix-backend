"""Recover unknown personal-care facings from labeled neighbors on the same shelf row."""

from __future__ import annotations

import re
from typing import Any

from app.planogram_guided import cluster_records_by_shelf_row

PC_ROW_BRANDS = frozenset(
    {
        "dove",
        "pantene",
        "nivea",
        "tresemme",
        "head",
        "sunsilk",
        "loreal",
        "dabur",
        "himalaya",
        "pears",
        "lux",
        "lifebuoy",
        "colgate",
        "closeup",
        "axe",
        "fogg",
        "gillette",
        "ponds",
        "vaseline",
        "medimix",
        "garnier",
        "oldspice",
        "parkavenue",
        "clinic",
        "meera",
        "joy",
        "mamaearth",
        "simple",
        "wildstone",
    }
)


def _norm_brand(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def _is_unknown(rec: dict) -> bool:
    brand = _norm_brand(rec.get("brand") or "")
    product = (rec.get("product_name") or "").lower()
    if brand in {"", "unknown"}:
        return True
    return product in {"", "unknown", "unidentified sku"}


def _pc_aisle_enabled(scan_context: dict | None) -> bool:
    if not scan_context:
        return False
    from app.scan_context import _normalize_key

    cat = _normalize_key(scan_context.get("aislix_category") or "")
    if cat == "personal care":
        return True
    return bool(scan_context.get("multi_sub_category_audit"))


def recover_pc_unknowns_by_row(
    classified: list[dict],
    scan_context: dict | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Assign unknown facings from same-row labeled neighbors on PC / multi-sub shelves."""
    stats: dict[str, Any] = {"pc_row_recovery": 0}
    if not _pc_aisle_enabled(scan_context):
        return classified, stats

    for cluster in cluster_records_by_shelf_row(classified):
        if len(cluster) < 2:
            continue
        labeled: dict[str, dict] = {}
        brand_counts: dict[str, int] = {}
        for rec in cluster:
            if _is_unknown(rec):
                continue
            brand = _norm_brand(rec.get("brand") or "")
            if brand in PC_ROW_BRANDS:
                labeled.setdefault(brand, rec)
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
        if not labeled:
            continue
        dominant_brand = max(brand_counts, key=brand_counts.get) if brand_counts else ""
        for rec in cluster:
            if not _is_unknown(rec):
                continue
            pack = (rec.get("pack_text") or "").lower()
            matched: dict | None = None
            for brand, ref in labeled.items():
                if brand in pack or (ref.get("brand") or "").lower() in pack:
                    matched = ref
                    break
            if not matched and brand_counts.get(dominant_brand, 0) >= 2:
                matched = labeled.get(dominant_brand)
            if not matched:
                continue
            rec.update(
                {
                    "brand": matched["brand"],
                    "product_name": matched["product_name"],
                    "sku": matched.get("sku") or "",
                    "category": matched.get("category") or "Personal Care",
                    "confidence": max(float(rec.get("confidence") or 0), 0.82),
                    "recognition_source": "pc_row_neighbor",
                }
            )
            stats["pc_row_recovery"] += 1

    if stats["pc_row_recovery"]:
        print(f"PC row recovery: {stats['pc_row_recovery']} facings from same-row neighbors")
    return classified, stats
