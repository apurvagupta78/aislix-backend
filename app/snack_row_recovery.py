"""Assign Lay's chip variants by shelf row + bag color when OCR is incomplete."""

from __future__ import annotations

import os
import re
from typing import Any

import numpy as np

from app.ocr_reader import load_facing_image
from app.planogram_guided import cluster_records_by_shelf_row

SNACK_ROW_RECOVERY = os.getenv("SNACK_ROW_RECOVERY", "true").lower() in {"1", "true", "yes"}

LAYS_FLAVOR_TOKENS = (
    "magic masala",
    "tomato tango",
    "cream",
    "onion",
    "american style",
    "classic salted",
    "india",
)

LAYS_ROW_PRODUCTS: dict[str, dict[str, str]] = {
    "blue": {
        "brand": "Lays",
        "product_name": "Indias Magic Masala Potato Chips",
        "sku": "lays_indias_magic_masala_potato_chips",
        "category": "Snacks",
    },
    "orange": {
        "brand": "Lays",
        "product_name": "Indias Magic Masala Potato Chips",
        "sku": "lays_indias_magic_masala_potato_chips",
        "category": "Snacks",
    },
    "red": {
        "brand": "Lays",
        "product_name": "Tomato Tango Potato Chips",
        "sku": "lays_tomato_tango_potato_chips",
        "category": "Snacks",
    },
    "green": {
        "brand": "Lays",
        "product_name": "American Style Cream and Onion Potato Chips",
        "sku": "lays_american_style_cream_and_onion_potato_chips",
        "category": "Snacks",
    },
}


def _norm_brand(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def _is_unknown_or_generic_lays(row: dict) -> bool:
    brand = _norm_brand(row.get("brand") or "")
    product = (row.get("product_name") or "").lower()
    if brand in {"", "unknown"}:
        return True
    if brand in {"lays"} and (
        "classic salted" in product
        or product in {"", "unknown", "unidentified sku", "potato chips", "lays"}
    ):
        return True
    return False


def _ocr_has_lays_flavor(ocr_text: str) -> bool:
    text = (ocr_text or "").lower()
    return any(token in text for token in LAYS_FLAVOR_TOKENS)


def _bag_color_family(source_image: np.ndarray, record: dict) -> str:
    """Classify bag color: blue/orange (Magic Masala), red (Tomato Tango), green (Cream & Onion)."""
    region = np.asarray(load_facing_image(record, source_image))
    h, w = region.shape[:2]
    y1, y2 = int(h * 0.15), int(h * 0.85)
    x1, x2 = int(w * 0.15), int(w * 0.85)
    if y2 <= y1 or x2 <= x1:
        return "unknown"
    sample = region[y1:y2, x1:x2]
    if sample.size == 0 or sample.ndim != 3:
        return "unknown"

    r = float(sample[:, :, 0].mean())
    g = float(sample[:, :, 1].mean())
    b = float(sample[:, :, 2].mean())

    # Order matters: green first, then orange (before warm red), then tomato tango dark blue.
    if g > 88 and g > r + 10 and g >= b - 8:
        return "green"
    if r > 105 and g > 65 and r > b + 25:
        return "orange"
    if r > 95 and r > g + 15 and r > b + 12:
        return "red"
    # Dark blue Tomato Tango — blue-dominant, low warmth (not Magic Masala orange-blue).
    if b > 95 and b > r + 18 and b > g + 12 and r < 85:
        return "red"
    # India's Magic Masala — blue-teal with warm orange undertone (not pure cool blue).
    if b > 85 and r > 65 and g > 45 and b >= r - 12 and b < r + 45:
        return "blue"
    return "unknown"


def _has_distinct_lays_flavor(row: dict) -> bool:
    product = (row.get("product_name") or "").lower()
    return any(
        token in product
        for token in ("magic masala", "tomato tango", "cream", "onion", "classic salted")
    )


def should_use_snack_row_recovery(
    classified: list[dict],
    scan_context: dict | None,
) -> bool:
    if not SNACK_ROW_RECOVERY or not scan_context:
        return False
    if scan_context.get("planogram_candidates"):
        return False
    sub = (scan_context.get("sub_category") or "").lower()
    if sub not in {"chips", "potato_chips"}:
        return False
    rows = cluster_records_by_shelf_row(classified)
    return len(rows) >= 2


def recover_snack_variants_by_row(
    classified: list[dict],
    source_image: np.ndarray,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Label unknown/generic Lay's facings from row-level bag color consensus."""
    stats: dict[str, Any] = {"snack_row_recovery": 0, "snack_row_rows": 0}
    if not should_use_snack_row_recovery(classified, scan_context):
        return classified, stats

    row_clusters = cluster_records_by_shelf_row(classified)
    stats["snack_row_rows"] = len(row_clusters)

    for cluster in row_clusters:
        if len(cluster) < 2:
            continue

        color_votes: dict[str, int] = {}
        for rec in cluster:
            color = _bag_color_family(source_image, rec)
            if color != "unknown":
                color_votes[color] = color_votes.get(color, 0) + 1

        if not color_votes:
            continue

        dominant_color = max(color_votes, key=color_votes.get)
        unknown_count = sum(1 for rec in cluster if _is_unknown_or_generic_lays(rec))
        min_ratio = 0.45 if unknown_count >= len(cluster) // 2 else 0.55
        if color_votes[dominant_color] / len(cluster) < min_ratio:
            continue

        product = LAYS_ROW_PRODUCTS.get(dominant_color)
        if not product:
            continue

        for rec in cluster:
            pack_text = (rec.get("pack_text") or "").strip()
            if _has_distinct_lays_flavor(rec) and not _is_unknown_or_generic_lays(rec):
                continue
            if _ocr_has_lays_flavor(pack_text) and not _is_unknown_or_generic_lays(rec):
                continue
            if not _is_unknown_or_generic_lays(rec):
                brand = _norm_brand(rec.get("brand") or "")
                if brand not in {"lays"}:
                    continue

            rec.update(
                {
                    "brand": product["brand"],
                    "product_name": product["product_name"],
                    "sku": product["sku"],
                    "category": product["category"],
                    "confidence": max(float(rec.get("confidence") or 0), 0.82),
                    "recognition_source": "snack_row_color",
                }
            )
            stats["snack_row_recovery"] += 1

    if stats["snack_row_recovery"]:
        print(
            f"Snack row recovery: {stats['snack_row_recovery']} facings "
            f"across {stats['snack_row_rows']} rows"
        )
    return classified, stats
