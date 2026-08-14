"""Parse YOLO class slugs into brand / product / variant metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"

SIZE_SUFFIXES = (
    "gms", "gm", "g", "kg", "ml", "ltr", "l", "unit", "units", "bags", "bag",
    "pcs", "pc", "pack", "packs",
)


def slug_to_metadata(slug: str) -> dict:
    tokens = [t for t in slug.lower().replace("-", "_").split("_") if t]
    if not tokens:
        return {"brand": "", "product_name": slug, "variant": "", "sku": slug, "category": "General"}

    brand = tokens[0].replace("'", "").title()
    variant_tokens: list[str] = []
    if len(tokens) >= 2:
        tail = tokens[-2:]
        if tail[-1] in SIZE_SUFFIXES or re.fullmatch(r"\d+", tail[-1] or ""):
            variant_tokens = tail
            body = tokens[1:-len(variant_tokens)]
        else:
            body = tokens[1:]
    else:
        body = []

    product_name = " ".join(body).title() if body else brand
    variant = " ".join(variant_tokens) if variant_tokens else ""

    return {
        "brand": brand,
        "product_name": product_name,
        "variant": variant,
        "sku": slug,
        "category": infer_category(slug),
    }


def infer_category(slug: str) -> str:
    s = slug.lower()
    rules = [
        (("tea", "coffee", "lipton", "tata_tea", "nescafe", "bru_"), "Beverages"),
        (("kulfi", "ice_cream", "funwich", "frozen_dessert", "sorbet", "gelato"), "General"),
        (("biscuit", "cookie", "marie", "rusk", "bread", "parota", "hearts"), "Bakery & Biscuits"),
        (("shampoo", "soap", "toothpaste", "deodorant", "deo", "lotion"), "Personal Care"),
        (("detergent", "dishwash", "cleaner", "harpic", "vim"), "Household"),
        (("oil", "ghee", "atta", "dal", "rice", "masala", "spice"), "Staples"),
        (("chocolate", "chips", "namkeen", "snack", "lays", "haldiram"), "Snacks"),
        (("milk", "dahi", "curd", "paneer", "cheese", "nestle_a"), "Dairy"),
        (("amul",), "Dairy"),
    ]
    for keys, category in rules:
        if any(k in s for k in keys):
            return category
    return "General"


def load_catalog() -> list[dict]:
    if not CATALOG_PATH.exists():
        return []
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("products", [])


def save_catalog(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump({"products": entries}, f, indent=2)
