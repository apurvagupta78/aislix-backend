"""Aggregate detections into inventory rows and frontend product payloads."""

from __future__ import annotations

import re
from collections import defaultdict

LOW_STOCK_THRESHOLD = 2

BRAND_DISPLAY_ALIASES: dict[str, str] = {
    "tresemmé": "Tresemme",
    "tresemm": "Tresemme",
    "tresenme": "Tresemme",
    "tresemrn": "Tresemme",
    "l'oreal": "L'Oreal",
    "l oreal": "L'Oreal",
    "head": "Head & Shoulders",
    "clinic": "Clinic Plus",
    "crax": "Crax",
    "lays": "Lays",
    "lay's": "Lays",
    "lay s": "Lays",
    "bingo": "Bingo",
    "bingo!": "Bingo",
    "kurkure": "Kurkure",
    "haldiram's": "Haldiram",
    "haldirams": "Haldiram",
    "pringles": "Pringles",
}

PRODUCT_DISPLAY_ALIASES: dict[str, str] = {
    "rings": "Rings",
    "curls": "Curls",
    "potato chips": "Potato Chips",
    "masala munch": "Masala Munch",
    "tedhe medhe": "Tedhe Medhe",
    "mad angles": "Mad Angles",
    "snacks": "Snacks",
    "wafers": "Wafers",
    "funwith": "Funwich",
    "funwich": "Funwich",
}

VARIANT_PLACEHOLDERS = frozenset({
    "",
    "unknown",
    "unidentified",
    "unidentified sku",
    "n/a",
    "na",
    "none",
})


def _normalize_variant_key(variant: str) -> str:
    v = re.sub(r"\s+", " ", (variant or "").strip().lower())
    if v in VARIANT_PLACEHOLDERS:
        return ""
    return v


def _display_variant(variant: str, existing: str = "") -> str:
    """Prefer a concrete variant string over placeholder values."""
    if existing and _normalize_variant_key(existing):
        return existing.strip()
    cleaned = (variant or "").strip()
    if _normalize_variant_key(cleaned):
        return cleaned
    return existing.strip() if existing else ""


def _normalize_brand_key(brand: str, product: str = "") -> str:
    brand_l = re.sub(r"[^\w\s&']", "", brand.lower().strip())
    brand_l = re.sub(r"\s+", " ", brand_l).strip()
    product_l = product.lower()
    if brand_l == "head" and "shoulder" in product_l:
        return "head & shoulders"
    if brand_l == "clinic" and "plus" in product_l:
        return "clinic plus"
    return BRAND_DISPLAY_ALIASES.get(brand_l, brand_l)


def _normalize_product_key(product: str) -> str:
    product_l = re.sub(r"\s+", " ", product.strip().lower())
    return PRODUCT_DISPLAY_ALIASES.get(product_l, product_l)


def _display_product_name(product: str) -> str:
    product_l = re.sub(r"\s+", " ", product.strip().lower())
    if product_l in PRODUCT_DISPLAY_ALIASES:
        return PRODUCT_DISPLAY_ALIASES[product_l]
    if product.isupper() and len(product) > 2:
        return product.title()
    return product.strip()


def _display_brand_name(brand: str, brand_key: str) -> str:
    if brand_key == "head & shoulders":
        return "Head & Shoulders"
    if brand_key == "clinic plus":
        return "Clinic Plus"
    alias_display = BRAND_DISPLAY_ALIASES.get(brand.lower().strip())
    if alias_display:
        return alias_display
    alias_display = BRAND_DISPLAY_ALIASES.get(brand_key)
    if alias_display:
        return alias_display
    return brand.strip()


def normalize_classified_labels(classified: list[dict]) -> list[dict]:
    """Canonical brand/product casing so facings aggregate into one SKU row."""
    normalized: list[dict] = []
    for item in classified:
        row = dict(item)
        brand = (row.get("brand") or "Unknown").strip()
        product = (row.get("product_name") or "Unknown").strip()
        brand_key = _normalize_brand_key(brand, product)
        row["brand"] = _display_brand_name(brand, brand_key)
        row["product_name"] = _display_product_name(product)
        row["variant"] = _display_variant(row.get("variant") or "")
        normalized.append(row)
    return normalized


def aggregate_inventory(classified: list[dict]) -> list[dict]:
    buckets: dict[tuple, dict] = defaultdict(lambda: {"quantity": 0, "confidences": []})

    for item in classified:
        brand = (item.get("brand") or "Unknown").strip()
        product = (item.get("product_name") or "Unknown").strip()
        variant = (item.get("variant") or "").strip()
        sku = (item.get("sku") or "").strip()
        brand_key = _normalize_brand_key(brand, product)
        product_key = _normalize_product_key(product)
        variant_key = _normalize_variant_key(variant)
        key = (brand_key, product_key, variant_key, sku.lower())
        bucket = buckets[key]
        bucket["brand"] = _display_brand_name(brand, brand_key)
        bucket["product_name"] = _display_product_name(product)
        bucket["variant"] = _display_variant(variant, bucket.get("variant") or "")
        bucket["category"] = item.get("category") or "General"
        bucket["sku"] = item.get("sku") or ""
        bucket["quantity"] += 1
        bucket["confidences"].append(float(item.get("confidence") or 0.0))
        if "x1" in item:
            bucket.setdefault("boxes", []).append(
                {
                    "x1": item["x1"],
                    "y1": item["y1"],
                    "x2": item["x2"],
                    "y2": item["y2"],
                }
            )

    inventory = []
    for bucket in buckets.values():
        avg_conf = sum(bucket["confidences"]) / max(len(bucket["confidences"]), 1)
        qty = bucket["quantity"]
        inventory.append(
            {
                "brand": bucket["brand"],
                "product_name": bucket["product_name"],
                "variant": bucket["variant"],
                "category": bucket["category"],
                "sku": bucket["sku"],
                "quantity": qty,
                "facings": qty,
                "confidence": round(avg_conf, 4),
                "stock_status": (
                    "low_stock" if qty <= LOW_STOCK_THRESHOLD else "in_stock"
                ),
            }
        )

    inventory.sort(key=lambda row: row["quantity"], reverse=True)
    return inventory


def inventory_to_api_products(inventory: list[dict]) -> list[dict]:
    """Aggregated SKU rows for the frontend (one row per brand/product/variant)."""
    products = []
    for row in inventory:
        products.append(
            {
                "brand": row["brand"],
                "product_name": row["product_name"],
                "name": row["product_name"],
                "variant": row.get("variant") or "",
                "category": row.get("category") or "General",
                "sku": row.get("sku") or "",
                "quantity": row["quantity"],
                "facings": row["facings"],
                "confidence": row["confidence"],
                "stock_status": row.get("stock_status") or "in_stock",
                "compliance_status": row.get("compliance_status") or "ok",
                "compliance_alert": row.get("compliance_alert") or "OK",
                "compliance_interpretation": row.get("compliance_interpretation") or "",
                "detected_sub_category_label": row.get("detected_sub_category_label") or "",
                "expected_sub_category_label": row.get("expected_sub_category_label") or "",
            }
        )
    return products


def expand_to_products(inventory: list[dict], classified: list[dict]) -> list[dict]:
    """One row per facing for Supabase detected_products normalization."""
    products = []
    for item in classified:
        qty = 1
        conf = float(item.get("confidence") or 0.0)
        brand = item.get("brand") or "Unknown"
        name = item.get("product_name") or "Unknown"
        products.append(
            {
                "brand": brand,
                "product_name": name,
                "name": name,
                "variant": item.get("variant") or "",
                "category": item.get("category") or "General",
                "sku": item.get("sku") or "",
                "quantity": qty,
                "facings": qty,
                "confidence": conf,
                "stock_status": "in_stock",
                "bounding_box": {
                    "x1": item.get("x1"),
                    "y1": item.get("y1"),
                    "x2": item.get("x2"),
                    "y2": item.get("y2"),
                },
            }
        )
    return products
