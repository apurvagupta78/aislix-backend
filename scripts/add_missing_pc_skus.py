"""Add missing personal care SKUs used by OCR/FAISS matching."""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"

NEW_SKUS = [
    {
        "class_id": 9001,
        "brand": "Pears",
        "product_name": "Pure And Gentle Soap",
        "variant": "125 g",
        "sku": "pears_pure_and_gentle_soap_125g",
        "category": "Personal Care",
    },
    {
        "class_id": 9002,
        "brand": "Pears",
        "product_name": "Germ Shield Soap",
        "variant": "125 g",
        "sku": "pears_germ_shield_soap_125g",
        "category": "Personal Care",
    },
    {
        "class_id": 9003,
        "brand": "Dettol",
        "product_name": "Original Hand Wash",
        "variant": "200 ml",
        "sku": "dettol_original_hand_wash_200ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9004,
        "brand": "Dettol",
        "product_name": "Skincare Hand Wash",
        "variant": "200 ml",
        "sku": "dettol_skincare_hand_wash_200ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9005,
        "brand": "Himalaya",
        "product_name": "Anti Hair Fall Shampoo",
        "variant": "180 ml",
        "sku": "himalaya_anti_hair_fall_shampoo_180ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9006,
        "brand": "Tresemme",
        "product_name": "Keratin Smooth Shampoo",
        "variant": "185 ml",
        "sku": "tresemme_keratin_smooth_shampoo_185ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9007,
        "brand": "Tresemme",
        "product_name": "Smooth Shine Shampoo",
        "variant": "180 ml",
        "sku": "tresemme_smooth_shine_shampoo_180ml",
        "category": "Personal Care",
    },
]


def main() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = data["products"] if isinstance(data, dict) else data
    existing_skus = {(p.get("sku") or "").lower() for p in products}
    added = 0
    for entry in NEW_SKUS:
        sku = entry["sku"]
        if sku.lower() in existing_skus:
            continue
        products.append(entry)
        existing_skus.add(sku.lower())
        added += 1
    if isinstance(data, dict):
        data["products"] = products
    CATALOG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added {added} new personal care SKU(s).")


if __name__ == "__main__":
    main()
