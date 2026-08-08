"""Brand and product lookup built from the FAISS catalog for OCR text matching."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.catalog import infer_category, load_catalog

_brands: list[str] | None = None
_brand_products: dict[str, list[dict]] | None = None
_brand_aliases: dict[str, str] | None = None

# OCR text often uses multi-word names; map to catalog brand keys.
TEXT_ALIASES: dict[str, str] = {
    "del monte": "Del",
    "tata tea": "Tata",
    "brooke bond": "Brooke",
    "red label": "Brooke",
    "yellow label": "Brooke",
    "taj mahal": "Taj",
    "tata gold": "Tata",
    "tata premium": "Tata",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _load() -> None:
    global _brands, _brand_products, _brand_aliases
    if _brands is not None:
        return
    products = load_catalog()
    brand_map: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for entry in products:
        brand = (entry.get("brand") or "").strip()
        if not brand or brand.lower() in {"unknown", "7"}:
            continue
        key = brand.lower()
        brand_map.setdefault(key, []).append(entry)
        seen.add(brand)
    _brand_products = brand_map
    _brands = sorted(seen, key=len, reverse=True)
    _brand_aliases = {k: v for k, v in TEXT_ALIASES.items()}


def all_brands() -> list[str]:
    _load()
    return _brands or []


def products_for_brand(brand: str) -> list[dict]:
    _load()
    return (_brand_products or {}).get(brand.lower(), [])


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_brand_in_text(text: str) -> tuple[str, float] | None:
    """Return (brand, confidence) if a catalog brand appears in OCR text."""
    _load()
    if not text or not _brands:
        return None
    normalized = _normalize(text)
    _load()
    for alias, brand in (_brand_aliases or {}).items():
        if alias in normalized:
            return brand, 0.9
    best_brand = ""
    best_score = 0.0
    for brand in _brands:
        brand_norm = _normalize(brand)
        if len(brand_norm) < 3:
            continue
        if brand_norm in normalized:
            score = min(0.99, 0.82 + len(brand_norm) / 100)
            if score > best_score:
                best_score = score
                best_brand = brand
        else:
            ratio = _similarity(brand, text)
            if ratio >= 0.88 and ratio > best_score:
                best_score = ratio
                best_brand = brand
    if best_brand and best_score >= 0.82:
        return best_brand, round(best_score, 4)
    return None


def match_product_for_brand(brand: str, text: str) -> dict | None:
    """Pick the best catalog SKU for a brand given OCR text."""
    entries = products_for_brand(brand)
    if not entries:
        return None
    normalized = _normalize(text)
    best: dict | None = None
    best_score = 0.0
    for entry in entries:
        product = (entry.get("product_name") or "").strip()
        variant = (entry.get("variant") or "").strip()
        sku = (entry.get("sku") or "").strip()
        haystack = " ".join(filter(None, [product, variant, sku.replace("_", " ")]))
        if not haystack:
            continue
        hay_norm = _normalize(haystack)
        if hay_norm in normalized or _normalize(product) in normalized:
            score = 0.92
        else:
            score = _similarity(haystack, text)
        if score > best_score:
            best_score = score
            best = entry
    if best and best_score >= 0.55:
        return {
            "brand": brand,
            "product_name": best.get("product_name") or brand,
            "variant": best.get("variant") or "",
            "sku": best.get("sku") or "",
            "category": best.get("category") or infer_category(best.get("sku") or ""),
            "confidence": round(min(0.98, best_score), 4),
            "recognition_source": "ocr",
        }
    return {
        "brand": brand,
        "product_name": brand,
        "variant": "",
        "sku": entries[0].get("sku") or "",
        "category": entries[0].get("category") or "General",
        "confidence": 0.78,
        "recognition_source": "ocr",
    }


def category_allows_brand(scan_category: str | None, brand: str, sku: str = "") -> bool:
    """Reject obvious cross-aisle FAISS false positives when scan category is set."""
    if not scan_category or not brand:
        return True
    cat = scan_category.lower()
    brand_l = brand.lower()
    sku_cat = infer_category(sku or brand_l).lower()

    tea_keys = ("tea", "beverage", "drink", "coffee")
    snack_keys = ("snack", "chip", "biscuit", "namkeen")
    if any(k in cat for k in tea_keys):
        snack_brands = {"mars", "lays", "lay's", "haldiram", "britannia", "parle", "biscoff"}
        if brand_l in snack_brands:
            return False
        if any(k in cat for k in tea_keys) and sku_cat == "beverages":
            return True
        if any(k in cat for k in tea_keys):
            tea_brands = {
                "lipton", "tetley", "tata", "tata tea", "brooke bond", "taj mahal",
                "tajmahal", "tata gold", "red label", "yellow label", "tazo",
            }
            if any(tb in brand_l for tb in tea_brands):
                return True
            if "tea" in brand_l or "tea" in (sku or "").lower():
                return True
    if any(k in cat for k in snack_keys):
        if brand_l in {"lipton", "tetley", "tropicana", "sofit"}:
            return False
    return True
