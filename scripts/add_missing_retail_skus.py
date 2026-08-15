"""Add missing retail SKUs for OCR/FAISS matching (PC + mixed snack facings)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.retail_sku import add_retail_skus  # noqa: E402

NEW_SKUS = [
    {
        "class_id": 9115,
        "brand": "Dabur",
        "product_name": "Vatika Health Shine Shampoo",
        "variant": "180 ml",
        "sku": "dabur_vatika_health_shine_shampoo_180_ml",
        "category": "Personal Care",
        "donor_hint": "tresemme smooth shine",
    },
    {
        "class_id": 9116,
        "brand": "Axe",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "axe_deodorant_body_spray_150_ml",
        "category": "Personal Care",
        "donor_hint": "deodorant body spray",
    },
    {
        "class_id": 9117,
        "brand": "Fogg",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "fogg_deodorant_body_spray_150_ml",
        "category": "Personal Care",
        "donor_hint": "deodorant body spray",
    },
    {
        "class_id": 9118,
        "brand": "Wild Stone",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "wild_stone_deodorant_body_spray_150_ml",
        "category": "Personal Care",
        "donor_hint": "deodorant body spray",
    },
    {
        "class_id": 9119,
        "brand": "Park Avenue",
        "product_name": "Deodorant Body Spray",
        "variant": "150 ml",
        "sku": "park_avenue_deodorant_body_spray_150_ml",
        "category": "Personal Care",
        "donor_hint": "deodorant body spray",
    },
    {
        "class_id": 9120,
        "brand": "Crax",
        "product_name": "Rings",
        "variant": "66 gms",
        "sku": "crax_rings_66_gms",
        "category": "Snacks",
        "donor_hint": "mad angles",
    },
    {
        "class_id": 9121,
        "brand": "Crax",
        "product_name": "Curls",
        "variant": "66 gms",
        "sku": "crax_curls_66_gms",
        "category": "Snacks",
        "donor_hint": "mad angles",
    },
    {
        "class_id": 9122,
        "brand": "Kurkure",
        "product_name": "Masala Munch",
        "variant": "68 gms",
        "sku": "kurkure_masala_munch_68_gms",
        "category": "Snacks",
        "donor_hint": "mad angles",
    },
    {
        "class_id": 9123,
        "brand": "Bingo",
        "product_name": "Tedhe Medhe",
        "variant": "33 gms",
        "sku": "bingo_tedhe_medhe_33_gms",
        "category": "Snacks",
        "donor_hint": "mad angles",
    },
    {
        "class_id": 9124,
        "brand": "Bingo",
        "product_name": "Mad Angles",
        "variant": "33 gms",
        "sku": "bingo_mad_angles_33_gms",
        "category": "Snacks",
        "donor_hint": "mad angles",
    },
]


def main() -> None:
    add_retail_skus(NEW_SKUS, faiss_mode="auto")


if __name__ == "__main__":
    main()
