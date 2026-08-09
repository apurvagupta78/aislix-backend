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
    "others": ["general"],
}

# Typical brands per aisle — used to reject obvious cross-aisle false positives.
AISLE_BRAND_HINTS: dict[str, set[str]] = {
    "beverages": {
        "lipton", "tetley", "tata", "brooke bond", "taj mahal", "red label", "yellow label",
        "nescafe", "bru", "coca cola", "pepsi", "frooti", "maaza", "real", "tropicana",
        "boost", "horlicks", "complan", "bournvita", "sprite", "fanta", "paper boat", "tang",
        "minute maid", "mirinda", "7up", "mountain dew",
    },
    "packaged food & snacks": {
        "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "sunfeast", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "too yumm", "act ii",
        "cadbury", "nestle", "amul", "itc", "priya gold", "snickers", "mars", "figaro",
    },
    "personal care": {
        "dove", "lux", "lifebuoy", "himalaya", "colgate", "pepsodent", "closeup",
        "head & shoulders", "pantene", "sunsilk", "gillette", "nivea", "ponds", "pond's",
        "dettol", "pears", "tresemme", "tresemmé", "sensodyne", "loreal", "l'oreal",
        "lakme", "lakmé", "clinic plus", "indulekha", "mamaearth", "garnier", "joy",
        "simple", "clear", "meera", "oral-b", "oral b", "tressemme",
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

# Food / snack brands that must not appear on personal care, home care, etc.
FOOD_SNACK_BRANDS: set[str] = {
    "snickers", "mars", "cadbury", "kitkat", "munch", "perk", "galaxy", "twix", "bounty",
    "figaro", "haldiram", "haldiram's", "britannia", "parle", "lays", "lay's", "kurkure",
    "bingo", "maggi", "maggie", "nutella", "american garden", "jabsons", "nutrela",
    "blue bird", "shan", "homelite", "knorr", "kellogg's", "kelloggs", "quaker",
}

# Brands that must never appear when a specific aisle category is selected.
AISLE_BRAND_BLOCKLIST: dict[str, set[str]] = {
    "beverages": {
        "mars", "cadbury", "snickers", "kitkat", "munch", "perk", "galaxy", "twix",
        "bounty", "haldiram", "haldiram's", "britannia", "parle", "bisk farm", "mtr",
        "maggi", "maggie", "lays", "lay's", "kurkure", "bingo", "sunfeast",
        "dove", "lux", "colgate", "pepsodent", "harpic", "vim", "surf excel", "sofit",
        "figaro",
    },
    "packaged food & snacks": {
        "lipton", "tetley", "coca cola", "pepsi", "sprite", "fanta", "tropicana", "mirinda",
    },
    "personal care": FOOD_SNACK_BRANDS
    | {
        "lipton", "tetley", "coca cola", "pepsi", "sprite", "fanta", "mirinda", "real",
        "surf excel", "ariel", "rin", "tide", "vim", "harpic",
    },
    "home care": FOOD_SNACK_BRANDS | {"lipton", "tetley", "coca cola", "pepsi", "dove", "colgate"},
    "health & wellness": FOOD_SNACK_BRANDS | {"lipton", "coca cola", "pepsi", "lays"},
    "dairy & chilled": {"dove", "lux", "colgate", "harpic", "surf excel", "lipton", "lays"},
}

# Sub-category blocklists (cross-type within aisle). Keys are normalized sub_category ids.
SUB_CATEGORY_BLOCKLIST: dict[str, set[str]] = {
    "tea": {
        "coca", "coca cola", "coca-cola", "pepsi", "fanta", "sprite", "real", "tropicana",
        "maaza", "frooti", "paper boat", "minute maid", "sofit", "mirinda", "7up",
    },
    "juices": {"lipton", "tetley", "tata", "brooke", "brooke bond"},
    "soft_drinks": {"lipton", "tetley", "tata", "brooke bond", "brooke"},
    "coffee": {"coca cola", "pepsi", "sprite", "fanta", "mirinda", "lipton", "tetley"},
    "water": {"lipton", "tetley", "coca cola", "pepsi", "snickers", "cadbury"},
}

# Expected brands when a narrow sub-category is selected (OCR can override).
SUB_CATEGORY_BRAND_HINTS: dict[str, dict[str, set[str]]] = {
    "personal care": {
        "shampoo": {
            "dove", "pantene", "sunsilk", "head & shoulders", "tresemme", "tresemmé",
            "clinic plus", "loreal", "l'oreal", "garnier", "indulekha", "himalaya",
            "clear", "meera", "sunsilk", "schwarzkopf",
        },
        "soap": {
            "lux", "dove", "dettol", "pears", "lifebuoy", "santoor", "hamam", "cinthol",
            "medimix", "margo", "fiama", "yardley",
        },
        "toothpaste": {
            "colgate", "pepsodent", "sensodyne", "closeup", "dabur", "himalaya", "oral-b",
            "oral b", "meswak",
        },
        "deodorant": {"axe", "denim", "park avenue", "fogg", "nivea", "dove", "rexona"},
        "skincare": {"nivea", "ponds", "pond's", "mamaearth", "garnier", "himalaya", "joy", "simple"},
        "cosmetics": {"lakme", "lakmé", "maybelline", "loreal", "l'oreal", "colorbar"},
        "shaving": {"gillette", "dorco", "bombay shaving", "park avenue"},
    },
    "beverages": {
        "tea": {"lipton", "tetley", "tata", "brooke bond", "taj mahal", "red label", "yellow label"},
        "coffee": {"nescafe", "bru", "davidoff", "continental"},
        "soft_drinks": {"coca cola", "pepsi", "sprite", "fanta", "mirinda", "7up", "mountain dew"},
        "juices": {"real", "tropicana", "paper boat", "b natural", "minute maid", "frooti", "maaza"},
    },
}

_categories: list[dict] | None = None
_name_index: dict[str, dict] | None = None


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _slug_key(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower().strip())).strip("_")


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


def resolve_subcategory_label(category: dict | None, sub_id: str | None) -> str | None:
    if not category or not sub_id:
        return None
    sub_key = _slug_key(sub_id)
    for sub in category.get("subcategories") or []:
        if _slug_key(sub.get("id") or "") == sub_key:
            return sub.get("label") or sub_id
    return sub_id.replace("_", " ").title()


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
    sub_category, sub_category_label, sub_category_custom = _resolve_sub_category(metadata, resolved)

    return {
        "store_id": (metadata.get("store_id") or "").strip() or None,
        "aislix_category": aislix_name or None,
        "aislix_category_id": aislix_id or None,
        "aislix_examples": (resolved or {}).get("examples") or "",
        "shelf_label": shelf_label or None,
        "location": (metadata.get("location") or shelf_label or "").strip() or None,
        "notes": (metadata.get("notes") or "").strip() or None,
        "sub_category": sub_category,
        "sub_category_label": sub_category_label,
        "sub_category_custom": sub_category_custom,
        "catalog_categories": catalog_cats,
        "brand_hints": brand_hints,
    }


def _resolve_sub_category(metadata: dict, category: dict | None) -> tuple[str | None, str | None, str | None]:
    raw = metadata.get("sub_category") or metadata.get("beverage_type") or metadata.get("product_type")
    custom = (metadata.get("sub_category_custom") or "").strip() or None
    label = (metadata.get("sub_category_label") or "").strip() or None

    if raw and str(raw).strip():
        sub_id = _slug_key(str(raw))
        if not label:
            label = resolve_subcategory_label(category, sub_id)
        return sub_id, label, custom

    notes = (metadata.get("notes") or "").lower()
    if "tea shelf" in notes or "tea aisle" in notes or notes.strip() == "tea":
        return "tea", "Tea", custom
    if "juice" in notes:
        return "juices", "Juices", custom
    if "soft drink" in notes or "cola" in notes:
        return "soft_drinks", "Soft drinks", custom

    if custom and category and _normalize_key(category.get("name") or "") == "others":
        return "others", custom, custom

    return None, None, custom


def _ocr_confirms_brand(brand_l: str, ocr_text: str) -> bool:
    if not ocr_text:
        return False
    text_l = ocr_text.lower()
    if brand_l in text_l or brand_l.replace("-", " ") in text_l:
        return True
    if brand_l == "coca" and ("coca cola" in text_l or "coca-cola" in text_l):
        return True
    return False


def sub_category_blocks_brand(context: dict | None, brand: str, ocr_text: str = "") -> bool:
    """Return True when brand should be rejected for this scan sub_category."""
    if not context or not brand:
        return False
    sub = context.get("sub_category")
    if not sub:
        return False

    brand_l = brand.lower().strip()
    if _ocr_confirms_brand(brand_l, ocr_text):
        return False

    blocklist = SUB_CATEGORY_BLOCKLIST.get(sub, set())
    if brand_l in blocklist:
        return True

    # Narrow sub-category hints are enforced strictly for beverages (tea vs cola),
    # but personal care shelves are often mixed (soap + shampoo on one photo).
    aislix_key = _normalize_key(context.get("aislix_category") or "")
    sub_hints = (SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}).get(sub)
    if sub_hints and sub != "others" and aislix_key == "beverages":
        general_hints = context.get("brand_hints") or set()
        if brand_l not in sub_hints and brand_l not in general_hints:
            return True

    return False


def gpt_context_prompt(context: dict | None) -> str:
    if not context or not context.get("aislix_category"):
        return ""
    name = context["aislix_category"]
    examples = context.get("aislix_examples") or ""
    shelf = context.get("shelf_label") or ""
    sub_label = context.get("sub_category_label") or ""
    sub_custom = context.get("sub_category_custom") or ""

    if sub_custom:
        sub_label = sub_custom
    elif not sub_label and context.get("sub_category"):
        sub_label = str(context["sub_category"]).replace("_", " ").title()

    lines = [
        f"\nScan context: this shelf photo is from the **{name}** aisle.",
        f"Sub-section: **{sub_label}**." if sub_label else "",
        f"Expected product types: {examples}." if examples else "",
        f"Location: {shelf}." if shelf else "",
    ]

    if _normalize_key(name) == "beverages":
        lines.append(
            "Only label beverages. Never label chocolate, biscuits, snacks, soap, or shampoo."
        )
    elif _normalize_key(name) == "personal care":
        lines.append(
            "Only label personal care products (shampoo, soap, toothpaste, skincare, etc.). "
            "Never label food, snacks, beverages, olives, peanuts, or chocolate."
        )
    elif _normalize_key(name) == "home care":
        lines.append("Only label home care / cleaning products. Never label food or beverages.")
    else:
        lines.append(
            f"Only label products that belong in {name}"
            + (f" — {sub_label}" if sub_label else "")
            + ". Reject obvious cross-aisle guesses."
        )

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
    resolved = resolve_aislix_category(str(category)) if category else None
    if required and not category:
        errors.append("category is required.")
    elif category and not resolved:
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

    sub = metadata.get("sub_category") or metadata.get("product_type")
    if required and resolved and (resolved.get("subcategories") or []) and not sub:
        if _normalize_key(resolved.get("name") or "") != "others":
            errors.append("sub_category is required.")

    if sub and _slug_key(str(sub)) == "others":
        custom = (metadata.get("sub_category_custom") or metadata.get("notes") or "").strip()
        if not custom:
            errors.append("sub_category_custom is required when sub_category is Others.")

    return errors


def categories_for_api() -> list[dict]:
    """Return category list with subcategories for GET /categories."""
    return load_aislix_categories()
