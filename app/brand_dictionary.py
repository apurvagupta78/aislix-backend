"""Brand and product lookup built from the FAISS catalog for OCR text matching."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.catalog import infer_category, load_catalog

_brands: list[str] | None = None
_brand_products: dict[str, list[dict]] | None = None
_brand_aliases: dict[str, str] | None = None

# OCR text often uses multi-word names; map to catalog brand keys (longest checked first).
TEXT_ALIASES: dict[str, str] = {
    "tata tea agni": "Tata",
    "tata tea gold": "Tata",
    "tata tea premium": "Tata",
    "del monte": "Del",
    "tata tea": "Tata",
    "brooke bond": "Brooke",
    "red label": "Brooke",
    "yellow label": "Brooke",
    "taj mahal": "Taj",
    "tata gold": "Tata",
    "tata premium": "Tata",
    "tea agni": "Tata",
}

# Distinctive pack text → brand + preferred catalog product (checked before generic brand match).
PRODUCT_HINTS: list[tuple[str, str, str]] = [
    (r"\btata\s+tea\s+agni\b", "Tata", "Tea Agni"),
    (r"\btea\s+agni\b", "Tata", "Tea Agni"),
    (r"\bagni\b", "Tata", "Tea Agni"),
    (r"\btata\s+tea\s+gold\b", "Tata", "Tea Gold"),
    (r"\blipton\b", "Lipton", ""),
    (r"\btetley\b", "Tetley", ""),
    (r"\bgreen\s+tea\b", "Lipton", "Green Tea"),
    (r"\bbrooke\s+bond\b", "Brooke", ""),
    (r"\bred\s+label\b", "Brooke", "Red Label"),
    (r"\byellow\s+label\b", "Brooke", "Yellow Label"),
    (r"\breal\b.*\bmango\b", "Real", "Mango Juice"),
    (r"\bmango\s+juice\b", "Real", "Mango Juice"),
    (r"\bcoca[\-\s]?cola\b", "Coca", "Coke"),
    (r"\bpepsi\b", "Pepsi", ""),
    (r"\bfanta\b", "Fanta", ""),
    (r"\bdettol\b", "Dettol", ""),
    (r"\bindulekha\b", "Indulekha", ""),
    (r"\bhimalaya\b", "Himalaya", ""),
    (r"\btresemme\b", "Tresemme", ""),
    (r"\btresemm[eé]\b", "Tresemme", ""),
]

TEA_OCR_MARKERS = (
    "lipton", "tetley", "tata tea", "tea agni", "agni", "green tea", "red label",
    "yellow label", "brooke bond", "taj mahal", "tea bags", "tea bag", "tea premix",
)
NON_TEA_BEVERAGE_BRANDS = {
    "sofit", "coca cola", "coca-cola", "pepsi", "fanta", "sprite", "tropicana", "maaza",
}


def pack_text_indicates_tea(text: str) -> bool:
    text_l = _normalize(text)
    return any(marker in text_l for marker in TEA_OCR_MARKERS)


def label_conflicts_with_tea_pack(label: dict, text: str) -> bool:
    if not text or not pack_text_indicates_tea(text):
        return False
    brand_l = (label.get("brand") or "").strip().lower()
    return brand_l in NON_TEA_BEVERAGE_BRANDS


def label_conflicts_with_pack_text(label: dict, text: str) -> bool:
    """True when OCR clearly names a different brand than the proposed label."""
    if not text or len(text.strip()) < 3:
        return False
    corrected = match_from_text(text)
    if not corrected:
        return False
    label_brand = (label.get("brand") or "").strip().lower()
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not label_brand or not text_brand or label_brand == text_brand:
        return False
    text_l = _normalize(text)
    if any(token in text_l for token in _brand_tokens(label.get("brand") or "")):
        return False
    return True


def _brand_tokens(brand: str) -> set[str]:
    brand_l = brand.lower().strip()
    tokens = {brand_l, brand_l.replace("-", " ")}
    if brand_l == "coca":
        tokens.add("coca cola")
        tokens.add("coca-cola")
    return tokens


def ocr_agrees_with_label(label: dict, text: str) -> bool:
    """Return True when OCR text supports the proposed brand/product label."""
    if not text or len(text.strip()) < 3:
        return True
    corrected = match_from_text(text)
    if not corrected:
        return False
    label_brand = (label.get("brand") or "").strip().lower()
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not label_brand or not text_brand:
        return False
    if label_brand == text_brand:
        return True
    if label_brand in text_brand or text_brand in label_brand:
        return True
    text_l = _normalize(text)
    return any(token in text_l for token in _brand_tokens(label.get("brand") or ""))


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


def _word_in_text(word: str, normalized: str) -> bool:
    if not word:
        return False
    return re.search(rf"\b{re.escape(word)}\b", normalized) is not None


def match_brand_in_text(text: str) -> tuple[str, float] | None:
    """Return (brand, confidence) if a catalog brand appears in OCR text."""
    _load()
    if not text or not _brands:
        return None
    normalized = _normalize(text)
    candidates: list[tuple[str, float, int]] = []

    for pattern, brand, _product in PRODUCT_HINTS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            span_len = len(re.search(pattern, normalized, flags=re.IGNORECASE).group(0))  # type: ignore[union-attr]
            candidates.append((brand, 0.94, span_len))

    for alias, brand in sorted((_brand_aliases or {}).items(), key=lambda item: -len(item[0])):
        if alias in normalized:
            candidates.append((brand, 0.91, len(alias)))

    for brand in _brands:
        brand_norm = _normalize(brand)
        if len(brand_norm) < 3:
            continue
        if _word_in_text(brand_norm, normalized):
            candidates.append((brand, min(0.99, 0.84 + len(brand_norm) / 100), len(brand_norm)))

    if candidates:
        candidates.sort(key=lambda item: (-item[2], -item[1]))
        return candidates[0][0], round(candidates[0][1], 4)

    best_brand = ""
    best_score = 0.0
    for brand in _brands:
        brand_norm = _normalize(brand)
        if len(brand_norm) < 5:
            continue
        ratio = _similarity(brand, text)
        if ratio >= 0.9 and ratio > best_score:
            best_score = ratio
            best_brand = brand
    if best_brand:
        return best_brand, round(best_score, 4)
    return None


def _catalog_entry(brand: str, product_name: str) -> dict | None:
    for entry in products_for_brand(brand):
        if (entry.get("product_name") or "").strip().lower() == product_name.lower():
            return entry
    return None


def match_from_text(text: str) -> dict | None:
    """Best catalog match from OCR text: product hints → brand → SKU."""
    if not text or len(text.strip()) < 3:
        return None
    normalized = _normalize(text)

    for pattern, brand, product_name in PRODUCT_HINTS:
        if not re.search(pattern, normalized, flags=re.IGNORECASE):
            continue
        if product_name:
            entry = _catalog_entry(brand, product_name)
            if entry:
                return {
                    "brand": brand,
                    "product_name": entry.get("product_name") or product_name,
                    "variant": entry.get("variant") or "",
                    "sku": entry.get("sku") or "",
                    "category": entry.get("category") or infer_category(entry.get("sku") or ""),
                    "confidence": 0.94,
                    "recognition_source": "ocr",
                    "visible_text": text[:240],
                }
        product = match_product_for_brand(brand, text)
        if product:
            product["visible_text"] = text[:240]
            product["confidence"] = max(float(product.get("confidence") or 0), 0.9)
            return product

    brand_match = match_brand_in_text(text)
    if not brand_match:
        return None
    brand, brand_conf = brand_match
    product = match_product_for_brand(brand, text)
    if not product:
        return None
    product["visible_text"] = text[:240]
    product["confidence"] = max(float(product.get("confidence") or 0), brand_conf)
    return product


def reconcile_label_with_text(label: dict, text: str) -> dict:
    """Override GPT/FAISS labels when pack text clearly names a different brand or SKU."""
    if not text or len(text.strip()) < 3:
        return label
    if label_conflicts_with_tea_pack(label, text):
        corrected = match_from_text(text)
        if corrected:
            merged = {**label, **corrected}
            merged["recognition_source"] = (label.get("recognition_source") or "faiss") + "+ocr_fix"
            merged["confidence"] = float(corrected.get("confidence") or 0.88)
            return merged
        return {
            **label,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "recognition_source": "ocr_reject",
        }
    corrected = match_from_text(text)
    if not corrected:
        return label

    current_brand = (label.get("brand") or "").strip().lower()
    text_brand = (corrected.get("brand") or "").strip().lower()
    if not text_brand or text_brand == current_brand:
        if corrected.get("product_name") and corrected.get("product_name") != label.get("product_name"):
            merged = {**label, **corrected}
            merged["recognition_source"] = label.get("recognition_source", "gpt") + "+ocr"
            merged["confidence"] = max(float(label.get("confidence") or 0), float(corrected.get("confidence") or 0))
            return merged
        return label

    # Pack text explicitly names a different brand (e.g. Lipton misread as Tata).
    merged = {**label, **corrected}
    merged["recognition_source"] = (label.get("recognition_source") or "gpt") + "+ocr_fix"
    merged["confidence"] = float(corrected.get("confidence") or 0.88)
    return merged


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
            for token in re.split(r"[\s\-]+", _normalize(product)):
                if len(token) >= 4 and _word_in_text(token, normalized):
                    score = max(score, 0.95)
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


def category_allows_brand(
    scan_category: str | None,
    brand: str,
    sku: str = "",
    entry_category: str = "",
    scan_context: dict | None = None,
) -> bool:
    """Reject obvious cross-aisle FAISS false positives when scan category is set."""
    from app.scan_context import resolve_scan_context, sku_allowed_in_context

    if scan_context:
        return sku_allowed_in_context(brand, sku=sku, entry_category=entry_category, context=scan_context)

    if not scan_category or not brand:
        return True

    ctx = resolve_scan_context({"category": scan_category})
    if ctx.get("aislix_category"):
        return sku_allowed_in_context(brand, sku=sku, entry_category=entry_category, context=ctx)

    cat = scan_category.lower()
    brand_l = brand.lower()
    sku_cat = infer_category(sku or brand_l).lower()

    tea_keys = ("tea", "beverage", "drink", "coffee")
    snack_keys = ("snack", "chip", "biscuit", "namkeen")
    if any(k in cat for k in tea_keys):
        snack_brands = {
            "mars", "lays", "lay's", "haldiram", "haldiram's", "britannia", "parle",
            "biscoff", "bisk farm", "mtr", "maggi", "maggie", "sunfeast",
        }
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
