"""Aggregate detections into inventory rows and frontend product payloads."""

from __future__ import annotations

from collections import defaultdict

LOW_STOCK_THRESHOLD = 2


def aggregate_inventory(classified: list[dict]) -> list[dict]:
    buckets: dict[tuple, dict] = defaultdict(lambda: {"quantity": 0, "confidences": []})

    for item in classified:
        brand = (item.get("brand") or "Unknown").strip()
        product = (item.get("product_name") or "Unknown").strip()
        variant = (item.get("variant") or "").strip()
        key = (brand.lower(), product.lower(), variant.lower())
        bucket = buckets[key]
        bucket["brand"] = brand
        bucket["product_name"] = product
        bucket["variant"] = variant
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
