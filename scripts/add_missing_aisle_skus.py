"""Add missing aisle SKUs for snacks, grocery, home care, and beverages."""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"

NEW_SKUS = [
    {
        "class_id": 9101,
        "brand": "Haldiram",
        "product_name": "Bhujia Sev",
        "variant": "200 g",
        "sku": "haldiram_bhujia_sev_200g",
        "category": "Snacks",
    },
    {
        "class_id": 9102,
        "brand": "Britannia",
        "product_name": "Good Day Butter Cookies",
        "variant": "200 g",
        "sku": "britannia_good_day_butter_cookies_200g",
        "category": "Snacks",
    },
    {
        "class_id": 9103,
        "brand": "Parle",
        "product_name": "G Glucose Biscuits",
        "variant": "250 g",
        "sku": "parle_g_glucose_biscuits_250g",
        "category": "Snacks",
    },
    {
        "class_id": 9104,
        "brand": "Maggi",
        "product_name": "2 Minute Masala Noodles",
        "variant": "70 g",
        "sku": "maggi_2_minute_masala_noodles_70g",
        "category": "Snacks",
    },
    {
        "class_id": 9105,
        "brand": "Lays",
        "product_name": "Classic Salted Potato Chips",
        "variant": "52 g",
        "sku": "lays_classic_salted_potato_chips_52g",
        "category": "Snacks",
    },
    {
        "class_id": 9106,
        "brand": "Surf",
        "product_name": "Excel Easy Wash Detergent Powder",
        "variant": "1 kg",
        "sku": "surf_excel_easy_wash_detergent_powder_1kg",
        "category": "Household",
    },
    {
        "class_id": 9107,
        "brand": "Harpic",
        "product_name": "Power Plus Toilet Cleaner",
        "variant": "500 ml",
        "sku": "harpic_power_plus_toilet_cleaner_500ml",
        "category": "Household",
    },
    {
        "class_id": 9108,
        "brand": "Vim",
        "product_name": "Dishwash Liquid Lemon",
        "variant": "500 ml",
        "sku": "vim_dishwash_liquid_lemon_500ml",
        "category": "Household",
    },
    {
        "class_id": 9109,
        "brand": "Aashirvaad",
        "product_name": "Shudh Chakki Atta",
        "variant": "5 kg",
        "sku": "aashirvaad_shudh_chakki_atta_5kg",
        "category": "Staples",
    },
    {
        "class_id": 9110,
        "brand": "Fortune",
        "product_name": "Soya Health Refined Oil",
        "variant": "1 l",
        "sku": "fortune_soya_health_refined_oil_1l",
        "category": "Staples",
    },
    {
        "class_id": 9111,
        "brand": "Nescafe",
        "product_name": "Classic Instant Coffee",
        "variant": "50 g",
        "sku": "nescafe_classic_instant_coffee_50g",
        "category": "Beverages",
    },
    {
        "class_id": 9112,
        "brand": "Bru",
        "product_name": "Instant Coffee",
        "variant": "50 g",
        "sku": "bru_instant_coffee_50g",
        "category": "Beverages",
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
    print(f"Added {added} new aisle SKU(s).")


if __name__ == "__main__":
    main()
