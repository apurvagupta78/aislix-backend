"""Add missing retail SKUs for OCR/FAISS matching (PC + mixed snack facings)."""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"

NEW_SKUS = [
    {
        "class_id": 9115,
        "brand": "Dabur",
        "product_name": "Vatika Health Shine Shampoo",
        "variant": "180 ml",
        "sku": "dabur_vatika_health_shine_shampoo_180_ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9116,
        "brand": "Axe",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "axe_deodorant_body_spray_150_ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9117,
        "brand": "Fogg",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "fogg_deodorant_body_spray_150_ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9118,
        "brand": "Wild Stone",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "wild_stone_deodorant_body_spray_150_ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9119,
        "brand": "Park Avenue",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "park_avenue_deodorant_body_spray_150_ml",
        "category": "Personal Care",
    },
    {
        "class_id": 9120,
        "brand": "Crax",
        "product_name": "Rings",
        "variant": "66 gms",
        "sku": "crax_rings_66_gms",
        "category": "Snacks",
    },
    {
        "class_id": 9121,
        "brand": "Crax",
        "product_name": "Curls",
        "variant": "66 gms",
        "sku": "crax_curls_66_gms",
        "category": "Snacks",
    },
    {
        "class_id": 9122,
        "brand": "Kurkure",
        "product_name": "Masala Munch",
        "variant": "68 gms",
        "sku": "kurkure_masala_munch_68_gms",
        "category": "Snacks",
    },
    {
        "class_id": 9123,
        "brand": "Bingo",
        "product_name": "Tedhe Medhe",
        "variant": "33 gms",
        "sku": "bingo_tedhe_medhe_33_gms",
        "category": "Snacks",
    },
    {
        "class_id": 9124,
        "brand": "Bingo",
        "product_name": "Mad Angles",
        "variant": "33 gms",
        "sku": "bingo_mad_angles_33_gms",
        "category": "Snacks",
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
        print(f"  + {entry['brand']} — {entry['product_name']}")
    if isinstance(data, dict):
        data["products"] = products
    CATALOG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added {added} new SKU(s) to catalog.json.")


if __name__ == "__main__":
    main()
