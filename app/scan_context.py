"""Scan location and aisle context for category-aware product recognition."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.catalog import infer_category

BASE_DIR = Path(__file__).resolve().parent.parent
CATEGORIES_PATH = BASE_DIR / "data" / "categories.json"

# Aislix retail aisle → catalog.json category values (lowercase).
AISLIX_TO_CATALOG: dict[str, list[str]] = {
    "beverages": ["beverages"],
    "fresh food": ["general"],
    "dairy & chilled": ["dairy"],
    "grocery & staples": ["staples"],
    "packaged food & snacks": ["snacks", "bakery & biscuits"],
    "frozen foods & ice cream": ["dairy", "general"],
    "personal care": ["personal care"],
    "home care": ["household"],
    "health & wellness": ["personal care", "general"],
    "baby & pet care": ["general", "dairy"],
}

# Typical brands per aisle — used to reject obvious cross-aisle false positives.
AISLE_BRAND_HINTS: dict[str, set[str]] = {
    "beverages": {
        "lipton", "tetley", "tata", "brooke bond", "taj mahal", "red label", "yellow label",
        "nescafe", "bru", "coca cola", "pepsi", "frooti", "maaza", "real", "tropicana",
        "boost", "horlicks", "complan", "bournvita", "sprite", "coca cola",
        "pepsi", "fanta", "paper boat", "tang", "minute maid",
    },
    "packaged food & snacks": {
        "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "sunfeast", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "too yumm", "act ii",
        "cadbury", "nestle", "amul", "itc", "priya gold",
    },
    "personal care": {
        "dove", "lux", "lifebuoy", "himalaya", "colgate", "pepsodent", "closeup",
        "head & shoulders", "pantene", "sunsilk", "gillette", "nivea", "ponds",
    },
    "home care": {
        "surf excel", "ariel", "rin", "tide", "vim", "harpic", "lizol", "domex",
        "good knight", "all out", "odonil", "airwick",
    },
    "dairy & chilled": {
        "amul", "mother dairy", "nestle", "britannia", "go", "epigamia", "yakult", "sofit",
    },
    "grocery & staples": {
        "india gate", "fortune", "saffola", "aashirvaad", "pillsbury", "mdh", "everest",
        "tata sampann", "patanjali", "24 mantra",
    },
}

# Brands that must never appear when a specific aisle category is selected.
AISLE_BRAND_BLOCKLIST: dict[str, set[str]] = {
    "beverages": {
        "mars", "cadbury", "snickers", "kitkat", "munch", "perk", "galaxy", "twix",
        "bounty", "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "sunfeast",
        "dove", "lux", "colgate", "pepsodent", "harpic", "vim", "surf excel",
        "sofit",
    },
    "packaged food & snacks": {
        "lipton", "tetley", "coca cola", "pepsi", "sprite", "fanta", "tropicana",
    },
    "personal care": {
        "lipton", "tetley", "coca cola", "pepsi", "haldiram", "lays",
    },
}

_categories: list[dict] | None = None
_name_index: dict[str, dict] | None = None


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def load_aislix_categories() -> list[dict]:
    global _categories, _name_index
    if _categories is not None:
        return _categories
    if not CATEGORIES_PATH.exists():
        _categories = []
        _name_index = {}
        return _categories
    with open(CATEGORIES_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    _categories = data if isinstance(data, list) else []
    _name_index = {_normalize_key(item.get("name") or ""): item for item in _categories}
    _name_index.update({_normalize_key(item.get("id") or ""): item for item in _categories})
    return _categories


def resolve_aislix_category(raw: str | None) -> dict | None:
    if not raw or not str(raw).strip():
        return None
    load_aislix_categories()
    return (_name_index or {}).get(_normalize_key(str(raw)))


def build_shelf_label(
    *,
    shelf_label: str | None = None,
    location: str | None = None,
    aisle: str | None = None,
    rack: str | None = None,
    bin_label: str | None = None,
) -> str:
    if shelf_label and shelf_label.strip():
        return shelf_label.strip()
    if location and location.strip():
        return location.strip()
    parts: list[str] = []
    if aisle and aisle.strip():
        parts.append(f"Aisle {aisle.strip()}" if not aisle.strip().lower().startswith("aisle") else aisle.strip())
    if rack and rack.strip():
        parts.append(f"Rack {rack.strip()}" if not rack.strip().lower().startswith("rack") else rack.strip())
    if bin_label and bin_label.strip():
        parts.append(f"Bin {bin_label.strip()}" if not bin_label.strip().lower().startswith("bin") else bin_label.strip())
    return " · ".join(parts)


def resolve_scan_context(metadata: dict | None) -> dict:
    """Normalize scan metadata from API / Lovable into a recognition context dict."""
    metadata = metadata or {}
    category_raw = metadata.get("category") or metadata.get("aislix_category")
    resolved = resolve_aislix_category(category_raw)
    aislix_name = (resolved or {}).get("name") or (str(category_raw).strip() if category_raw else "")
    aislix_id = (resolved or {}).get("id") or ""

    shelf_label = build_shelf_label(
        shelf_label=metadata.get("shelf_label"),
        location=metadata.get("location"),
        aisle=metadata.get("aisle"),
        rack=metadata.get("rack"),
        bin_label=metadata.get("bin"),
    )

    catalog_cats = AISLIX_TO_CATALOG.get(_normalize_key(aislix_name), [])
    brand_hints = AISLE_BRAND_HINTS.get(_normalize_key(aislix_name), set())

    return {
        "store_id": (metadata.get("store_id") or "").strip() or None,
        "aislix_category": aislix_name or None,
        "aislix_category_id": aislix_id or None,
        "aislix_examples": (resolved or {}).get("examples") or "",
        "shelf_label": shelf_label or None,
        "location": (metadata.get("location") or shelf_label or "").strip() or None,
        "notes": (metadata.get("notes") or "").strip() or None,
        "catalog_categories": catalog_cats,
        "brand_hints": brand_hints,
    }


def gpt_context_prompt(context: dict | None) -> str:
    if not context or not context.get("aislix_category"):
        return ""
    name = context["aislix_category"]
    examples = context.get("aislix_examples") or ""
    shelf = context.get("shelf_label") or ""
    lines = [
        f"\nScan context: this shelf photo is from the **{name}** aisle.",
        f"Expected product types: {examples}." if examples else "",
        f"Location: {shelf}." if shelf else "",
        "Only label products that belong in this aisle. Never label chocolate, biscuits, "
        "snacks, or personal-care brands on a Beverages shelf.",
    ]
    return "\n".join(line for line in lines if line)


def sku_allowed_in_context(
    brand: str,
    sku: str = "",
    entry_category: str = "",
    context: dict | None = None,
) -> bool:
    """Return False for obvious cross-aisle FAISS / GPT false positives."""
    if not context or not context.get("aislix_category"):
        return True
    if not brand:
        return True

    brand_l = brand.lower().strip()
    aislix_key = _normalize_key(context["aislix_category"])
    allowed_catalog = context.get("catalog_categories") or []
    hints = context.get("brand_hints") or set()
    blocklist = AISLE_BRAND_BLOCKLIST.get(aislix_key, set())

    if brand_l in blocklist:
        return False

    sku_cat = (entry_category or infer_category(sku or brand_l)).lower()

    if allowed_catalog and sku_cat not in {"", "general"}:
        if sku_cat in allowed_catalog:
            return True
        if sku_cat == "general":
            pass
        else:
            # Dairy/snacks catalog entries must not pass on a beverages aisle just via hints.
            if brand_l in hints and sku_cat.lower() not in {"dairy", "snacks", "personal care", "household"}:
                return True
            return False

    other_aisle_brands: set[str] = set()
    for aisle_key, brands in AISLE_BRAND_HINTS.items():
        if aisle_key != aislix_key:
            other_aisle_brands.update(brands)

    if brand_l in other_aisle_brands and brand_l not in hints:
        return False

    return True


def validate_scan_metadata(metadata: dict | None) -> list[str]:
    """Return list of validation errors. Empty = ok."""
    required = os.getenv("SCAN_CONTEXT_REQUIRED", "false").lower() in {"1", "true", "yes"}
    metadata = metadata or {}
    errors: list[str] = []

    category = metadata.get("category") or metadata.get("aislix_category")
    if required and not category:
        errors.append("category is required.")
    elif category and not resolve_aislix_category(str(category)):
        errors.append(f"Unknown category: {category}")

    if required and not metadata.get("store_id"):
        errors.append("store_id is required.")

    shelf_label = build_shelf_label(
        shelf_label=metadata.get("shelf_label"),
        location=metadata.get("location"),
        aisle=metadata.get("aisle"),
        rack=metadata.get("rack"),
        bin_label=metadata.get("bin"),
    )
    if required and not shelf_label:
        errors.append("location is required.")

    return errors
