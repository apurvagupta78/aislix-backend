"""Category / sub-category scoping for learned SKU FAISS search (Phase 2C)."""

from __future__ import annotations

import re
from typing import Any

from app.scan_context import (
    load_aislix_categories,
    normalize_sub_category_id,
    resolve_aislix_category,
    sub_categories_match,
)
from app.sku_category_map import map_class_to_aislix_category

LEARNED_SEARCH_K = 32


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _parse_category_label(category: str) -> tuple[str | None, str | None]:
    """Parse 'Beverages · Tea' → (category_id, sub_category_id)."""
    if not category or "·" not in category:
        return None, None
    parts = [p.strip() for p in category.replace("\u00b7", "·").split("·") if p.strip()]
    if len(parts) < 2:
        return None, None
    cat_name, sub_name = parts[0], parts[1]
    resolved = resolve_aislix_category(cat_name)
    if not resolved:
        return None, None
    cat_id = str(resolved.get("id") or "")
    sub_id = normalize_sub_category_id(sub_name, resolved.get("name"))
    return cat_id or None, sub_id or None


def _infer_from_brand(entry: dict[str, Any]) -> tuple[str, str]:
    """Map brand / product tokens to Aislix category ids via Grocer-Help rules."""
    for key in ("brand", "product_name", "sku"):
        raw = (entry.get(key) or "").strip()
        if not raw:
            continue
        mapped = map_class_to_aislix_category(raw.replace(" ", "_"))
        if mapped.get("category_id") and mapped["category_id"] != "others":
            return mapped["category_id"], mapped.get("sub_category_id") or "others"
    mapped = map_class_to_aislix_category(
        ((entry.get("brand") or entry.get("sku") or "unknown").replace(" ", "_"))
    )
    return mapped["category_id"], mapped.get("sub_category_id") or "others"


def effective_entry_ids(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolved category_id + sub_category_id for a learned catalog row."""
    cat_id = entry.get("category_id")
    sub_id = entry.get("sub_category_id")
    if cat_id and sub_id and sub_id != "others":
        return str(cat_id), str(sub_id)

    parsed_cat, parsed_sub = _parse_category_label(str(entry.get("category") or ""))
    if parsed_cat and parsed_cat != "others":
        cat_id = cat_id or parsed_cat
        if parsed_sub and parsed_sub != "others":
            sub_id = sub_id or parsed_sub

    inferred_cat, inferred_sub = _infer_from_brand(entry)
    if not cat_id or cat_id == "others":
        cat_id = inferred_cat
    if not sub_id or sub_id == "others":
        sub_id = inferred_sub if inferred_sub != "others" else (sub_id or parsed_sub or "others")

    return cat_id, sub_id


def enrich_learned_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Ensure category_id / sub_category_id are set on a learned SKU row."""
    cat_id, sub_id = effective_entry_ids(entry)
    if cat_id:
        entry["category_id"] = cat_id
    if sub_id:
        entry["sub_category_id"] = sub_id
    return entry


def entry_matches_scope(
    entry: dict[str, Any],
    scan_context: dict[str, Any] | None,
    *,
    strict_sub: bool = True,
) -> bool:
    """True when learned SKU is in the scan's category (and sub-category when set)."""
    if not scan_context:
        return True

    scan_cat = scan_context.get("aislix_category_id")
    if not scan_cat:
        return True

    entry_cat, entry_sub = effective_entry_ids(entry)
    if not entry_cat or entry_cat != scan_cat:
        return False

    scan_sub = scan_context.get("sub_category")
    if not strict_sub or not scan_sub or scan_sub == "others":
        return True

    category_name = scan_context.get("aislix_category")
    if sub_categories_match(entry_sub, scan_sub, category_name):
        return True

    # Re-check brand-inferred sub (handles Grocer-Help rows tagged Others · Others).
    _, inferred_sub = _infer_from_brand(entry)
    return sub_categories_match(inferred_sub, scan_sub, category_name)


def filter_scoped_candidates(
    catalog: list[dict],
    ids: list[int],
    scores: list[float],
    scan_context: dict[str, Any] | None,
    *,
    strict_sub: bool = True,
    threshold: float = 0.0,
) -> tuple[dict | None, float]:
    """Pick best catalog entry from FAISS ids that passes category scope."""
    best_entry: dict | None = None
    best_score = 0.0
    for idx, score in zip(ids, scores):
        if idx < 0 or score < threshold:
            continue
        entry = catalog[int(idx)]
        if scan_context and not entry_matches_scope(entry, scan_context, strict_sub=strict_sub):
            continue
        if score > best_score:
            best_entry = dict(entry)
            best_score = float(score)
    return best_entry, best_score


def catalog_entry_in_scope(entry: dict[str, Any], scan_context: dict[str, Any] | None) -> bool:
    """Filter base FAISS catalog hits using the same aisle scope as learned search."""
    if not scan_context:
        return True
    if not scan_context.get("aislix_category_id"):
        from app.brand_dictionary import category_allows_brand

        return category_allows_brand(
            scan_context.get("aislix_category"),
            entry.get("brand") or "",
            entry.get("sku") or "",
            entry_category=entry.get("category") or "",
            scan_context=scan_context,
        )

    pseudo = {
        "brand": entry.get("brand") or "",
        "product_name": entry.get("product_name") or "",
        "variant": entry.get("variant") or "",
        "sku": entry.get("sku") or "",
        "category": entry.get("category") or "",
    }
    enrich_learned_entry(pseudo)
    if entry_matches_scope(pseudo, scan_context, strict_sub=True):
        return True
    if scan_context.get("sub_category") and scan_context.get("sub_category") != "others":
        return entry_matches_scope(pseudo, scan_context, strict_sub=False)
    return False


def filter_candidates_by_scope(
    candidates: list[tuple[dict, float]],
    scan_context: dict[str, Any] | None,
) -> list[tuple[dict, float]]:
    """Drop FAISS/learned candidates outside the scan category scope."""
    if not scan_context or not scan_context.get("aislix_category_id"):
        return candidates
    return [(match, score) for match, score in candidates if catalog_entry_in_scope(match, scan_context)]


def ensure_categories_loaded() -> None:
    load_aislix_categories()
