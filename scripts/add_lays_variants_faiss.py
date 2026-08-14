#!/usr/bin/env python3
"""Add missing Lay's chip variants to catalog.json and append FAISS embeddings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import faiss
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import load_catalog, save_catalog  # noqa: E402
from app.clip_embeddings import embed_pil_images  # noqa: E402

DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
INDEX_PATH = DATA_DIR / "faiss.index"
DEFAULT_REF = DATA_DIR / "reference" / "lays_rack_a1l.jpg"

EMBEDDINGS_PER_SKU = 10

NEW_LAYS_VARIANTS = [
    {
        "class_id": 9113,
        "brand": "Lays",
        "product_name": "Tomato Tango Potato Chips",
        "variant": "",
        "sku": "lays_tomato_tango_potato_chips",
        "category": "Snacks",
        # Normalized row bands (y1, y2) on the A-1-L reference rack photo.
        "row_bands": [(0.50, 0.66)],
    },
    {
        "class_id": 9114,
        "brand": "Lays",
        "product_name": "American Style Cream and Onion Potato Chips",
        "variant": "",
        "sku": "lays_american_style_cream_and_onion_potato_chips",
        "category": "Snacks",
        "row_bands": [(0.66, 0.82), (0.82, 0.98)],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add Lay's variants and rebuild FAISS append.")
    parser.add_argument("--image", type=Path, default=DEFAULT_REF, help="Reference shelf photo")
    parser.add_argument("--embeddings-per-sku", type=int, default=EMBEDDINGS_PER_SKU)
    return parser.parse_args()


def _load_products() -> tuple[dict | list, list[dict]]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = raw["products"] if isinstance(raw, dict) else raw
    return raw, products


def _augment_variants(crop: Image.Image) -> list[Image.Image]:
    """Light augmentations so FAISS has multiple reference vectors per SKU."""
    base = crop.convert("RGB")
    out = [base]
    out.append(ImageEnhance.Contrast(base).enhance(1.35))
    out.append(ImageEnhance.Sharpness(base).enhance(1.4))
    out.append(base.filter(ImageFilter.SHARPEN))
    flipped = base.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    out.append(flipped)
    out.append(ImageEnhance.Contrast(flipped).enhance(1.3))
    bright = ImageEnhance.Brightness(base).enhance(1.12)
    out.append(bright)
    out.append(ImageEnhance.Contrast(bright).enhance(1.25))
    return out


def _grid_crops(image: Image.Image, row_bands: list[tuple[float, float]], cols: int = 6) -> list[Image.Image]:
    width, height = image.size
    crops: list[Image.Image] = []
    x_margin = 0.04
    col_width = (1.0 - 2 * x_margin) / cols
    for y1f, y2f in row_bands:
        y1 = int(height * y1f)
        y2 = int(height * y2f)
        for col in range(cols):
            x1f = x_margin + col * col_width
            x2f = x1f + col_width * 0.92
            x1 = int(width * x1f)
            x2 = int(width * x2f)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            crops.append(image.crop((x1, y1, x2, y2)))
    return crops


def _collect_embedding_crops(
    image: Image.Image,
    row_bands: list[tuple[float, float]],
    target: int,
) -> list[Image.Image]:
    seeds = _grid_crops(image, row_bands)
    if not seeds:
        raise RuntimeError("No crops extracted from reference image — check row bands.")
    selected: list[Image.Image] = []
    idx = 0
    while len(selected) < target:
        seed = seeds[idx % len(seeds)]
        augments = _augment_variants(seed)
        selected.append(augments[(len(selected) // len(seeds)) % len(augments)])
        idx += 1
    return selected[:target]


def main() -> None:
    args = parse_args()
    if not args.image.exists():
        raise SystemExit(f"Reference image not found: {args.image}")
    if not INDEX_PATH.exists():
        raise SystemExit(f"FAISS index not found: {INDEX_PATH}")

    raw, products = _load_products()
    existing_skus = {(p.get("sku") or "").lower() for p in products}

    to_add = [v for v in NEW_LAYS_VARIANTS if v["sku"].lower() not in existing_skus]
    if not to_add:
        print("All Lay's variants already present in catalog — nothing to add.")
        return

    image = Image.open(args.image).convert("RGB")
    print(f"Reference image: {args.image} ({image.size[0]}x{image.size[1]})")

    new_catalog_rows: list[dict] = []
    all_crops: list[Image.Image] = []

    for variant in to_add:
        crops = _collect_embedding_crops(image, variant["row_bands"], args.embeddings_per_sku)
        print(f"  {variant['product_name']}: {len(crops)} crops")
        for _crop in crops:
            all_crops.append(_crop)
            new_catalog_rows.append(
                {
                    "class_id": variant["class_id"],
                    "brand": variant["brand"],
                    "product_name": variant["product_name"],
                    "variant": variant["variant"],
                    "sku": variant["sku"],
                    "category": variant["category"],
                }
            )

    print(f"Embedding {len(all_crops)} new reference crops...")
    embeddings = embed_pil_images(all_crops)
    new_matrix = np.vstack(embeddings).astype(np.float32)
    faiss.normalize_L2(new_matrix)

    base_index = faiss.read_index(str(INDEX_PATH))
    base_matrix = base_index.reconstruct_n(0, base_index.ntotal)
    merged_matrix = np.vstack([base_matrix, new_matrix]).astype(np.float32)
    faiss.normalize_L2(merged_matrix)

    merged_index = faiss.IndexFlatIP(merged_matrix.shape[1])
    merged_index.add(merged_matrix)

    products.extend(new_catalog_rows)
    if isinstance(raw, dict):
        raw["products"] = products
        save_catalog(products)
    else:
        save_catalog(products)
        raw = products

    faiss.write_index(merged_index, str(INDEX_PATH))
    print(f"Added {len(new_catalog_rows)} embeddings for {len(to_add)} Lay's SKU(s).")
    print(f"Catalog size: {len(products)} | FAISS ntotal: {merged_index.ntotal}")


if __name__ == "__main__":
    main()
