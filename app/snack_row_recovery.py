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
    """Classify bag color: blue (Magic Masala), red (Tomato Tango), green (Cream & Onion)."""
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

    # Green Cream & Onion — allow warm lighting and blue freezer cast.
    if g > 75 and g >= r - 18 and g >= b - 35:
        if (g - min(r, b)) >= 5 or (g > r and g > b - 10):
            return "green"
    # Warm orange/red Tomato Tango — not greenish packs.
    if r > 95 and r > g + 15 and r > b + 10 and g < r - 5:
        return "red"
    if r > 105 and g > 65 and r > b + 25 and g < r - 5:
        return "red"
    # Cool blue-dominant Tomato — skip when green channel is strong (Cream & Onion under blue light).
    if b > 85 and b >= r and (b - r) >= 8 and r < 95 and g < r + 5:
        return "red"
    # Dark blue Tomato Tango — blue-dominant, low warmth (not Magic Masala orange-blue).
    if b > 95 and b > r + 18 and b > g + 12 and r < 85:
        return "red"
    # India's Magic Masala — blue-teal with warm orange undertone (not pure cool blue).
    if b > 85 and r > 65 and g > 45 and b >= r - 12 and b < r + 45:
        return "blue"
    return "unknown"


def _lays_color_for_product(row: dict) -> str | None:
    product = (row.get("product_name") or "").lower()
    if "magic masala" in product or ("india" in product and "masala" in product):
        return "blue"
    if "tomato tango" in product or "tomato" in product:
        return "red"
    if ("cream" in product and "onion" in product) or "cream & onion" in product:
        return "green"
    return None


def _color_families_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    # Legacy alias: older votes may still emit "orange" for tomato rows.
    if {a, b} <= {"red", "orange"}:
        return True
    return False


def _color_label_mismatch(rec: dict, bag_color: str) -> bool:
    """True when facing label color family disagrees with sampled bag pixels."""
    if bag_color in {"", "unknown"}:
        return False
    label_color = _lays_color_for_product(rec)
    if not label_color:
        return False
    return not _color_families_compatible(label_color, bag_color)


def _should_skip_row_recovery(rec: dict, dominant_color: str) -> bool:
    """Skip only when OCR flavor already matches row bag color."""
    product = (rec.get("product_name") or "").lower()
    if "magic masala" in product and dominant_color in {"red", "green", "orange"}:
        return False
    if "tomato" in product and dominant_color == "green":
        return False
    if ("cream" in product or "onion" in product) and dominant_color == "red":
        return False
    pack_text = (rec.get("pack_text") or "").strip()
    pack_lower = pack_text.lower()
    current_color = _lays_color_for_product(rec)
    if current_color and not _color_families_compatible(current_color, dominant_color):
        return False
    if _has_distinct_lays_flavor(rec) and not _is_unknown_or_generic_lays(rec):
        if dominant_color == "green" and "tomato" in product:
            return False
        if dominant_color == "red" and ("cream" in product or "onion" in product):
            return False
        if dominant_color == "blue" and ("cream" in product or "onion" in product):
            return False
        if dominant_color == "blue" and "tomato" in product:
            return False
        if dominant_color == "green" and (
            "magic masala" in product or ("india" in product and "masala" in product)
        ):
            return False
        return True
    if _ocr_has_lays_flavor(pack_text) and not _is_unknown_or_generic_lays(rec):
        if dominant_color == "green" and "tomato" in pack_lower:
            return False
        if dominant_color == "red" and ("cream" in pack_lower or "onion" in pack_lower):
            return False
        return True
    if not _is_unknown_or_generic_lays(rec):
        brand = _norm_brand(rec.get("brand") or "")
        if brand not in {"lays"}:
            return True
    return False


def _is_top_partial_facing(rec: dict, image_height: int) -> bool:
    """Top-of-shelf partial facings — keep unknown when OCR was weak."""
    if image_height <= 0:
        return False
    y_center = (int(rec.get("y1") or 0) + int(rec.get("y2") or 0)) / 2.0
    return y_center < image_height * 0.14


def _should_force_row_reconcile(rec: dict, dominant_color: str) -> bool:
    """Force row color when OCR flavor clearly disagrees with bag color consensus."""
    current_color = _lays_color_for_product(rec)
    if not current_color:
        return True
    if not _color_families_compatible(current_color, dominant_color):
        return True
    if "magic masala" in (rec.get("product_name") or "").lower() and dominant_color in {
        "red",
        "green",
        "orange",
    }:
        return True
    product_lower = (rec.get("product_name") or "").lower()
    if "tomato" in product_lower and dominant_color == "green":
        return True
    if ("cream" in product_lower or "onion" in product_lower) and dominant_color == "red":
        return True
    return False


def _has_distinct_lays_flavor(row: dict) -> bool:
    product = (row.get("product_name") or "").lower()
    return any(
        token in product
        for token in ("magic masala", "tomato tango", "cream", "onion", "classic salted")
    )


def should_use_snack_row_recovery(
    classified: list[dict],
    scan_context: dict | None,
    *,
    override_only: bool = False,
) -> bool:
    if not SNACK_ROW_RECOVERY or not scan_context:
        return False
    sub = (scan_context.get("sub_category") or "").lower()
    if sub not in {"chips", "potato_chips"}:
        return False
    if override_only:
        return True
    if scan_context.get("planogram_candidates") and not override_only:
        return False
    rows = cluster_records_by_shelf_row(classified)
    return len(rows) >= 2


def recover_snack_variants_by_row(
    classified: list[dict],
    source_image: np.ndarray,
    scan_context: dict | None = None,
    *,
    override_only: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    """Label unknown/generic Lay's facings from row-level bag color consensus."""
    stats: dict[str, Any] = {"snack_row_recovery": 0, "snack_row_rows": 0}
    if not should_use_snack_row_recovery(classified, scan_context, override_only=override_only):
        return classified, stats

    row_clusters = cluster_records_by_shelf_row(classified)
    stats["snack_row_rows"] = len(row_clusters)
    image_height = int(source_image.shape[0]) if source_image is not None else 0

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

        normalized_votes: dict[str, int] = {}
        for color, count in color_votes.items():
            key = "red" if color == "orange" else color
            normalized_votes[key] = normalized_votes.get(key, 0) + count

        dominant_color = max(normalized_votes, key=normalized_votes.get)
        unknown_count = sum(1 for rec in cluster if _is_unknown_or_generic_lays(rec))
        min_ratio = 0.45 if unknown_count >= len(cluster) // 2 else 0.55
        force_ratio = 0.5
        dominant_ratio = normalized_votes[dominant_color] / len(cluster)
        if dominant_ratio < min_ratio:
            continue

        product = LAYS_ROW_PRODUCTS.get(dominant_color)
        if not product:
            continue

        for rec in cluster:
            if _is_top_partial_facing(rec, image_height) and _is_unknown_or_generic_lays(rec):
                if float(rec.get("confidence") or 0) < 0.55:
                    continue
            force = dominant_ratio >= force_ratio and _should_force_row_reconcile(rec, dominant_color)
            if override_only and not force and not _color_label_mismatch(rec, dominant_color):
                continue
            if _should_skip_row_recovery(rec, dominant_color) and not force:
                continue

            rec.update(
                {
                    "brand": product["brand"],
                    "product_name": product["product_name"],
                    "sku": product["sku"],
                    "category": product["category"],
                    "confidence": max(float(rec.get("confidence") or 0), 0.84 if force else 0.82),
                    "recognition_source": "snack_row_color_force" if force else "snack_row_color",
                }
            )
            stats["snack_row_recovery"] += 1

    if override_only and source_image is not None:
        for rec in classified:
            bag_color = _bag_color_family(source_image, rec)
            if bag_color == "unknown":
                continue
            if _is_top_partial_facing(rec, image_height) and not _is_unknown_or_generic_lays(rec):
                if _color_label_mismatch(rec, bag_color):
                    rec.update(
                        {
                            "brand": "Unknown",
                            "product_name": "Unidentified SKU",
                            "sku": "",
                            "confidence": min(float(rec.get("confidence") or 0.35), 0.4),
                            "recognition_source": "top_partial_demote",
                        }
                    )
                    stats["snack_row_recovery"] += 1
                continue
            if not _color_label_mismatch(rec, bag_color):
                continue
            product = LAYS_ROW_PRODUCTS.get(bag_color)
            if not product:
                continue
            rec.update(
                {
                    "brand": product["brand"],
                    "product_name": product["product_name"],
                    "sku": product["sku"],
                    "category": product["category"],
                    "confidence": max(float(rec.get("confidence") or 0), 0.84),
                    "recognition_source": "snack_row_color_force",
                }
            )
            stats["snack_row_recovery"] += 1

    if stats["snack_row_recovery"]:
        print(
            f"Snack row recovery: {stats['snack_row_recovery']} facings "
            f"across {stats['snack_row_rows']} rows"
        )
    return classified, stats
