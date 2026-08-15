"""Catalog-aware OCR spell correction for retail pack text."""

from __future__ import annotations

import os
import re
from difflib import get_close_matches
from functools import lru_cache

from app.brand_dictionary import PRODUCT_HINTS, TEXT_ALIASES
from app.catalog import load_catalog

SPELL_CORRECT_ENABLED = os.getenv("OCR_SPELL_CORRECT", "true").lower() in {"1", "true", "yes"}
SPELL_CUTOFF = float(os.getenv("OCR_SPELL_CUTOFF", "0.82"))
MIN_TOKEN_LEN = int(os.getenv("OCR_SPELL_MIN_TOKEN_LEN", "4"))


@lru_cache(maxsize=1)
def catalog_vocabulary() -> frozenset[str]:
    """Tokens from FAISS catalog, brand aliases, and product hint patterns."""
    words: set[str] = set()
    for entry in load_catalog():
        for field in ("brand", "product_name", "variant", "sku"):
            blob = (entry.get(field) or "").lower()
            words.update(re.findall(r"[a-z0-9]{3,}", blob))
    for alias in TEXT_ALIASES:
        words.update(re.findall(r"[a-z0-9]{3,}", alias.lower()))
    for pattern, brand, product in PRODUCT_HINTS:
        words.update(re.findall(r"[a-z0-9]{3,}", brand.lower()))
        words.update(re.findall(r"[a-z0-9]{3,}", product.lower()))
        words.update(re.findall(r"[a-z]{3,}", pattern.lower()))
    retail_common = {
        "shampoo", "conditioner", "masala", "noodles", "biscuits", "cookies",
        "chips", "cream", "onion", "tomato", "tango", "magic", "india", "indian",
        "original", "classic", "fresh", "organic", "premium", "gold", "green",
        "juice", "milk", "bread", "atta", "oil", "soap", "wash", "gel", "powder",
        "ml", "gram", "grams", "litre", "liter", "pack", "free", "style",
        "american", "potato", "lays", "maggi", "amul", "haldiram", "britannia",
        "brooke", "tetley", "lipton", "dove", "nivea", "pantene", "sunsilk",
    }
    words.update(retail_common)
    return frozenset(words)


def _preserve_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def spell_correct_ocr_text(text: str) -> str:
    """Fix near-miss OCR tokens using catalog vocabulary."""
    if not SPELL_CORRECT_ENABLED or not text or len(text.strip()) < 3:
        return text

    vocab = catalog_vocabulary()
    vocab_list = sorted(vocab)
    corrected: list[str] = []

    for token in text.split():
        core = re.sub(r"[^a-zA-Z0-9]", "", token)
        if len(core) < MIN_TOKEN_LEN:
            corrected.append(token)
            continue
        lower = core.lower()
        if lower in vocab:
            corrected.append(token)
            continue
        matches = get_close_matches(lower, vocab_list, n=1, cutoff=SPELL_CUTOFF)
        if matches:
            corrected.append(_preserve_case(core, matches[0]))
        else:
            corrected.append(token)

    return " ".join(corrected)


def enrich_ocr_with_catalog_phrases(text: str) -> str:
    """Append catalog brand/product tokens when partial OCR matches a SKU."""
    if not text or len(text.strip()) < 5:
        return text
    from app.brand_dictionary import match_from_text, normalize_ocr_text

    normalized = normalize_ocr_text(spell_correct_ocr_text(text))
    direct = match_from_text(normalized)
    if direct and float(direct.get("confidence") or 0) >= 0.88:
        return normalized

    best_text = normalized
    best_conf = float(direct.get("confidence") or 0) if direct else 0.0
    tokens = normalized.split()
    for width in range(min(5, len(tokens)), 1, -1):
        for start in range(len(tokens) - width + 1):
            window = " ".join(tokens[start : start + width])
            match = match_from_text(window)
            if match and float(match.get("confidence") or 0) > best_conf:
                best_conf = float(match["confidence"])
                brand = (match.get("brand") or "").strip()
                product = (match.get("product_name") or "").strip()
                parts = [normalized]
                if brand and brand.lower() not in normalized:
                    parts.insert(0, brand)
                if product and product.split()[0].lower() not in normalized:
                    parts.append(product)
                best_text = " ".join(parts)
    return re.sub(r"\s+", " ", best_text).strip()
