"""Correct common Astra CV brand OCR misreads before Aislix calc."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = frozenset(
    {"", "unverifiable", "unknown", "unidentified", "n/a", "na", "none", "null", "-", "—"}
)

# Common OCR confusions for Lay's wordmark / logo text on chip bags.
_LAYS_BRAND_ALIASES = frozenset(
    {
        "louis",
        "loui's",
        "loui",
        "lou is",
        "lay",
        "lays",
        "lay s",
        "lay5",
        "lay's",
    }
)

_LAYS_VARIANT_MARKERS = (
    r"magic\s+masala",
    r"tomato\s+tango",
    r"cream\s*(?:&|and)\s*onion",
    r"classic\s+salted",
    r"west\s*indies\s+hot\s*[n&]\s*sweet\s+chilli",
    r"spanish\s+tomato\s+tango",
)

_CHIP_PRODUCT = re.compile(r"\b(chips?|potato\s+chips?|crisps?)\b", re.I)
_LAYS_VARIANT_RE = re.compile("|".join(_LAYS_VARIANT_MARKERS), re.I)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def canonicalize_shelf_cv_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mutate product rows in place; return the same list for chaining."""
    for row in products:
        if not isinstance(row, dict):
            continue
        brand = _norm(row.get("brand"))
        variant = _norm(row.get("variant"))
        product = _norm(row.get("product_name") or row.get("product"))
        looks_like_lays_flavor = bool(variant and _LAYS_VARIANT_RE.search(variant))
        looks_like_chips = bool(product and _CHIP_PRODUCT.search(product))
        if brand in _LAYS_BRAND_ALIASES and (looks_like_lays_flavor or looks_like_chips):
            row["brand"] = "Lay's"
            if _norm(row.get("brand_status")) in _PLACEHOLDER:
                row["brand_status"] = "IDENTIFIED"
        elif looks_like_lays_flavor and (brand in _PLACEHOLDER or brand in _LAYS_BRAND_ALIASES):
            row["brand"] = "Lay's"
            row["brand_status"] = "IDENTIFIED"
    return products
