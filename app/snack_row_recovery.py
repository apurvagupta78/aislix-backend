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

MIXED_SNACK_BRANDS = frozenset(
    {"crax", "kurkure", "bingo", "pringles", "haldiram", "balaji", "tooyumm", "too yumm"}
)

OTHER_SNACK_OCR_MARKERS = (
    "kurkure",
    "bingo",
    "crax",
    "pringles",
    "tedhe medhe",
    "mad angles",
    "masala munch",
    "rings",
    "curls",
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


def _is_non_lays_snack_brand(rec: dict) -> bool:
    brand = _norm_brand(rec.get("brand") or "")
    return brand in MIXED_SNACK_BRANDS


def _pack_text_indicates_other_snack(text: str) -> bool:
    text_l = (text or "").lower()
    if re.search(r"lay(?:'|s)?s\b", text_l):
        return False
    return any(marker in text_l for marker in OTHER_SNACK_OCR_MARKERS)


def _facing_indicates_lays(rec: dict) -> bool:
    if _norm_brand(rec.get("brand") or "") == "lays":
        return True
    combined = f"{rec.get('pack_text') or ''} {rec.get('product_name') or ''}".lower()
    return bool(re.search(r"lay(?:'|s)?s\b", combined))


def _row_allows_lays_color_recovery(cluster: list[dict]) -> bool:
    """Lay's color→SKU mapping only on Lay's-dominant rows, not mixed-brand racks."""
    if any(_is_non_lays_snack_brand(rec) for rec in cluster):
        return False
    for rec in cluster:
        if _pack_text_indicates_other_snack(rec.get("pack_text") or ""):
            return False
    if any(_facing_indicates_lays(rec) for rec in cluster):
        return True
    if all(_is_unknown_or_generic_lays(rec) for rec in cluster):
        return True
    return False


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
    # Avoid shelf lip (bottom), frame bleed (left/right), and logo band (top).
    y1, y2 = int(h * 0.12), int(h * 0.72)
    x1, x2 = int(w * 0.20), int(w * 0.80)
    if y2 <= y1 or x2 <= x1:
        return "unknown"
    sample = region[y1:y2, x1:x2]
    if sample.size == 0 or sample.ndim != 3:
        return "unknown"

    r = float(sample[:, :, 0].mean())
    g = float(sample[:, :, 1].mean())
    b = float(sample[:, :, 2].mean())

    # Green Cream & Onion — warm/yellow-green under store lighting.
    if g > 68 and g >= r - 24 and g >= b - 42:
        if (g - min(r, b)) >= 3 or (g > r and g > b - 15):
            return "green"
    if g > 62 and r > 58 and g >= b - 28 and g >= r - 12 and (g - b) >= -5:
        return "green"
    # Warm orange/red Tomato Tango — low blue channel (not blue Magic Masala packs).
    if r > 95 and r > g + 12 and r > b + 22 and g < r - 5:
        return "red"
    if r > 120 and r > b + 18 and g < r - 5:
        return "red"
    # India's Magic Masala — blue/teal packs (dominant blue; warm or cool lighting).
    if b > 75 and b >= g - 15:
        if b >= r - 20 or (b > r and b > 70):
            return "blue"
    return "unknown"


def _row_color_consensus(
    cluster: list[dict],
    source_image: np.ndarray,
    *,
    min_ratio: float = 0.55,
) -> str | None:
    """Dominant bag color for a shelf row when votes are consistent."""
    votes: dict[str, int] = {}
    for rec in cluster:
        color = _bag_color_family(source_image, rec)
        if color != "unknown":
            votes[color] = votes.get(color, 0) + 1
    if not votes:
        return None
    dominant = max(votes, key=votes.get)
    if votes[dominant] / len(cluster) < min_ratio:
        return None
    return dominant


def _effective_bag_color(
    rec: dict,
    source_image: np.ndarray,
    row_color: str | None = None,
) -> str:
    """Per-facing color, falling back to unimodal row consensus when pixels are ambiguous."""
    facing_color = _bag_color_family(source_image, rec)
    if facing_color != "unknown":
        return facing_color
    return row_color or "unknown"


def _is_weak_tomato_pack_text(text: str) -> bool:
    """Partial OCR like 'Tom' / 'Tomato' must not override green/blue bag color."""
    blob = re.sub(r"\s+", " ", (text or "").lower().strip())
    if not blob or re.search(r"\blay(?:'|s)?s\b", blob):
        return False
    if "tomato tango" in blob:
        return False
    return bool(re.search(r"\btom(?:ato)?\b|\btango\b|\btom\b", blob))


def _apply_lays_product(rec: dict, color: str, source: str, *, confidence_floor: float = 0.84) -> bool:
    product = LAYS_ROW_PRODUCTS.get(color)
    if not product:
        return False
    rec.update(
        {
            **product,
            "confidence": max(float(rec.get("confidence") or 0), confidence_floor),
            "recognition_source": source,
        }
    )
    return True


def mark_top_partial_exclusions(
    classified: list[dict],
    source_image: np.ndarray | None,
    scan_context: dict | None = None,
) -> tuple[list[dict], int]:
    """Top-of-rack partial facings are outside the planogram band — exclude from inventory counts."""
    if source_image is None or not _snack_aisle_mixed_recovery_enabled(scan_context):
        return classified, 0
    sub = ((scan_context or {}).get("sub_category") or "").lower()
    if sub not in {"chips", "potato_chips"}:
        return classified, 0

    image_height = int(source_image.shape[0])
    excluded = 0
    for rec in classified:
        if not _is_top_partial_facing(rec, image_height):
            continue
        if rec.get("exclude_from_inventory"):
            continue
        rec["exclude_from_inventory"] = True
        rec["recognition_source"] = (rec.get("recognition_source") or "detect") + "+top_partial_exclude"
        excluded += 1
    if excluded:
        print(f"Lay's top-partial exclusion: {excluded} facing(s) omitted from inventory")
    return classified, excluded


def finalize_lays_rack_labels(
    classified: list[dict],
    source_image: np.ndarray | None,
    scan_context: dict | None = None,
) -> tuple[list[dict], int]:
    """
    Final Lay's rack reconciliation: row color + bag pixels beat weak tomato OCR fragments.
    Fixes green→Tomato Tango mislabels; never promotes top-partial facings into SKU counts.
    """
    if source_image is None or not _snack_aisle_mixed_recovery_enabled(scan_context):
        return classified, 0

    sub = ((scan_context or {}).get("sub_category") or "").lower()
    if sub not in {"chips", "potato_chips"}:
        return classified, 0

    fixed = 0
    image_height = int(source_image.shape[0])
    row_clusters = cluster_records_by_shelf_row(classified)
    row_colors: dict[int, str | None] = {}
    for cluster in row_clusters:
        for rec in cluster:
            row_colors[id(rec)] = _row_color_consensus(cluster, source_image, min_ratio=0.45)

    for rec in classified:
        if _is_top_partial_facing(rec, image_height) or rec.get("exclude_from_inventory"):
            continue
        if _is_non_lays_snack_brand(rec) or _pack_text_indicates_other_snack(rec.get("pack_text") or ""):
            continue
        if not _facing_indicates_lays(rec) and not _is_unknown_or_generic_lays(rec):
            continue

        row_color = row_colors.get(id(rec))
        bag_color = _effective_bag_color(rec, source_image, row_color)
        product = (rec.get("product_name") or "").lower()
        pack = (rec.get("pack_text") or "").lower()
        label_color = _lays_color_for_product(rec)

        # Unimodal green row beats one misread red facing or weak tomato OCR.
        if row_color == "green" and (
            label_color == "red"
            or "tomato" in product
            or _is_weak_tomato_pack_text(pack)
        ):
            bag_color = "green"
        effective_color = bag_color if bag_color != "unknown" else (row_color or "unknown")
        if effective_color == "unknown":
            continue

        label_color = label_color or _lays_color_for_product(rec)

        needs_fix = False
        if label_color and not _color_families_compatible(label_color, effective_color):
            needs_fix = True
        elif effective_color == "green" and ("tomato" in product or _is_weak_tomato_pack_text(pack)):
            needs_fix = True
        elif effective_color == "blue" and ("tomato" in product or "cream" in product):
            needs_fix = True
        elif effective_color == "red" and ("magic masala" in product or ("cream" in product and "onion" in product)):
            needs_fix = True

        if needs_fix and _apply_lays_product(rec, effective_color, "snack_row_finalize"):
            fixed += 1

    if fixed:
        print(f"Lay's rack finalize: corrected {fixed} facing(s)")
    return classified, fixed


def _lays_color_for_product(row: dict) -> str | None:
    product = (row.get("product_name") or "").lower()
    if "magic masala" in product or ("india" in product and "masala" in product):
        return "blue"
    if "tomato tango" in product or "tomato" in product:
        return "red"
    if ("cream" in product and "onion" in product) or "cream & onion" in product:
        return "green"
    if "cream" in product or "onion" in product:
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
        if dominant_color == "blue" and ("cream" in pack_lower or "onion" in pack_lower):
            return False
        return True
    if _is_non_lays_snack_brand(rec):
        return True
    if _pack_text_indicates_other_snack(pack_text):
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
    if _is_non_lays_snack_brand(rec):
        return False
    if _pack_text_indicates_other_snack(rec.get("pack_text") or ""):
        return False
    if not _is_unknown_or_generic_lays(rec):
        brand = _norm_brand(rec.get("brand") or "")
        if brand != "lays":
            return False
    current_color = _lays_color_for_product(rec)
    if not current_color:
        return _is_unknown_or_generic_lays(rec)
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


def _is_row_unknown(rec: dict) -> bool:
    brand = _norm_brand(rec.get("brand") or "")
    product = (rec.get("product_name") or "").lower()
    if brand in {"", "unknown"}:
        return True
    return product in {"", "unknown", "unidentified sku"}


def _recover_mixed_snack_unknowns(
    row_clusters: list[list[dict]],
    stats: dict[str, Any],
) -> None:
    """Assign unknown facings from labeled snack neighbors on the same shelf row."""
    for cluster in row_clusters:
        if len(cluster) < 2:
            continue
        labeled: dict[str, dict] = {}
        brand_counts: dict[str, int] = {}
        for rec in cluster:
            if _is_row_unknown(rec):
                continue
            brand = _norm_brand(rec.get("brand") or "")
            if brand in MIXED_SNACK_BRANDS | {"lays"}:
                labeled.setdefault(brand, rec)
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
        if not labeled:
            continue
        dominant_brand = max(brand_counts, key=brand_counts.get) if brand_counts else ""
        for rec in cluster:
            if not _is_row_unknown(rec):
                continue
            pack = (rec.get("pack_text") or "").lower()
            matched: dict | None = None
            for brand, ref in labeled.items():
                if brand == "lays":
                    if re.search(r"lay(?:'|s)?s\b", pack):
                        matched = ref
                        break
                elif brand in pack:
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
                    "category": matched.get("category") or "Snacks",
                    "confidence": max(float(rec.get("confidence") or 0), 0.82),
                    "recognition_source": "snack_row_neighbor",
                }
            )
            stats["snack_row_recovery"] += 1


def enforce_snack_color_and_brand_labels(
    classified: list[dict],
    source_image: np.ndarray | None,
    scan_context: dict | None = None,
) -> tuple[list[dict], int]:
    """Fix Lay's/Bingo/Crax cross-labels using bag color and pack text."""
    if source_image is None or not _snack_aisle_mixed_recovery_enabled(scan_context):
        return classified, 0
    fixed = 0
    row_clusters = cluster_records_by_shelf_row(classified)
    row_colors: dict[int, str | None] = {}
    for cluster in row_clusters:
        consensus = _row_color_consensus(cluster, source_image, min_ratio=0.45)
        for rec in cluster:
            row_colors[id(rec)] = consensus

    for rec in classified:
        if _is_row_unknown(rec) or rec.get("exclude_from_inventory"):
            continue
        brand = _norm_brand(rec.get("brand") or "")
        row_color = row_colors.get(id(rec))
        bag_color = _effective_bag_color(rec, source_image, row_color)
        product = (rec.get("product_name") or "").lower()
        pack = (rec.get("pack_text") or "").lower()
        label_color = _lays_color_for_product(rec)
        if row_color == "green" and (
            label_color == "red" or "tomato" in product or _is_weak_tomato_pack_text(pack)
        ):
            bag_color = "green"
        if bag_color == "unknown":
            continue

        if brand == "bingo" and bag_color in {"green", "blue", "red"}:
            if "tedhe" in product or "mad angles" in product or "mad angle" in product:
                lays_product = LAYS_ROW_PRODUCTS.get(bag_color)
                if lays_product:
                    rec.update(
                        {
                            **lays_product,
                            "confidence": max(float(rec.get("confidence") or 0), 0.84),
                            "recognition_source": "snack_color_brand_fix",
                        }
                    )
                    fixed += 1
                    continue

        if brand == "lays" and _color_label_mismatch(rec, bag_color):
            lays_product = LAYS_ROW_PRODUCTS.get(bag_color)
            if lays_product and not _pack_text_indicates_other_snack(pack):
                rec.update(
                    {
                        **lays_product,
                        "confidence": max(float(rec.get("confidence") or 0), 0.84),
                        "recognition_source": "snack_color_brand_fix",
                    }
                )
                fixed += 1
                continue

        if brand == "lays" and bag_color == "green" and ("tomato" in product or _is_weak_tomato_pack_text(pack)):
            if _apply_lays_product(rec, "green", "snack_color_brand_fix"):
                fixed += 1
                continue

        if brand in MIXED_SNACK_BRANDS and bag_color in {"green", "blue", "red"}:
            if re.search(r"lay(?:'|s)?s\b", pack):
                lays_product = LAYS_ROW_PRODUCTS.get(bag_color)
                if lays_product:
                    rec.update(
                        {
                            **lays_product,
                            "confidence": max(float(rec.get("confidence") or 0), 0.84),
                            "recognition_source": "snack_color_brand_fix",
                        }
                    )
                    fixed += 1

    if fixed:
        print(f"Snack color/brand enforcement: corrected {fixed} facing(s)")
    return classified, fixed


def _snack_aisle_mixed_recovery_enabled(scan_context: dict | None) -> bool:
    if not SNACK_ROW_RECOVERY or not scan_context:
        return False
    from app.scan_context import _normalize_key

    return _normalize_key(scan_context.get("aislix_category") or "") == "packaged food & snacks"


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
    row_clusters = cluster_records_by_shelf_row(classified)
    stats["snack_row_rows"] = len(row_clusters)

    if not should_use_snack_row_recovery(classified, scan_context, override_only=override_only):
        if _snack_aisle_mixed_recovery_enabled(scan_context):
            _recover_mixed_snack_unknowns(row_clusters, stats)
            if stats["snack_row_recovery"]:
                print(
                    f"Snack row recovery: {stats['snack_row_recovery']} facings "
                    f"across {stats['snack_row_rows']} rows"
                )
        return classified, stats

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

        if not _row_allows_lays_color_recovery(cluster):
            continue

        for rec in cluster:
            if _is_top_partial_facing(rec, image_height):
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
        row_dominant_color: dict[int, str] = {}
        for cluster in row_clusters:
            votes: dict[str, int] = {}
            for rec in cluster:
                color = _bag_color_family(source_image, rec)
                if color != "unknown":
                    votes[color] = votes.get(color, 0) + 1
            if not votes:
                continue
            dominant = max(votes, key=votes.get)
            for rec in cluster:
                row_dominant_color[id(rec)] = dominant

        for rec in classified:
            row_color = row_dominant_color.get(id(rec))
            label_color = _lays_color_for_product(rec)
            if row_color and label_color and _color_families_compatible(label_color, row_color):
                continue

            bag_color = _bag_color_family(source_image, rec)
            if row_color and label_color and not _color_families_compatible(label_color, row_color):
                bag_color = row_color
            elif bag_color == "unknown" and row_color:
                bag_color = row_color
            if bag_color == "unknown":
                continue
            if _is_top_partial_facing(rec, image_height):
                if _is_unknown_or_generic_lays(rec):
                    continue
                if not _color_label_mismatch(rec, bag_color):
                    continue
                if _is_non_lays_snack_brand(rec) or _pack_text_indicates_other_snack(rec.get("pack_text") or ""):
                    continue
                product = LAYS_ROW_PRODUCTS.get(bag_color)
                if product and _facing_indicates_lays(rec):
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
                continue
            if not _color_label_mismatch(rec, bag_color):
                continue
            if _is_non_lays_snack_brand(rec) or _pack_text_indicates_other_snack(rec.get("pack_text") or ""):
                continue
            if not _facing_indicates_lays(rec) and not _is_unknown_or_generic_lays(rec):
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

    if _snack_aisle_mixed_recovery_enabled(scan_context):
        _recover_mixed_snack_unknowns(row_clusters, stats)

    if stats["snack_row_recovery"]:
        print(
            f"Snack row recovery: {stats['snack_row_recovery']} facings "
            f"across {stats['snack_row_rows']} rows"
        )
    return classified, stats
