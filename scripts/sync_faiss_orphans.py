#!/usr/bin/env python3
"""Append FAISS embeddings for catalog rows that have no index vector yet."""

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

from app.clip_embeddings import embed_pil_images  # noqa: E402
from scripts.yolo_dataset import collect_class_crops, DEFAULT_DATASET  # noqa: E402

DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
INDEX_PATH = DATA_DIR / "faiss.index"

SKU_DONOR_HINTS: dict[str, str] = {
    "lays_tomato_tango_potato_chips": "magic masala",
    "lays_american_style_cream_and_onion_potato_chips": "classic salted",
    "nescafe_classic_instant_coffee_50g": "nescafe classic",
    "bru_instant_coffee_50g": "bru instant",
    "loreal_paris_total_repair_5_shampoo_180ml": "loreal color protect shampoo",
    "dabur_vatika_health_shine_shampoo_180_ml": "tresemme smooth shine",
    "fogg_deodorant_body_spray_150_ml": "deodorant body spray",
    "axe_deodorant_body_spray_150_ml": "deodorant body spray",
    "wild_stone_deodorant_body_spray_150_ml": "deodorant body spray",
    "park_avenue_deodorant_body_spray_150_ml": "deodorant body spray",
    "crax_rings_66_gms": "mad angles",
    "crax_curls_66_gms": "mad angles",
    "kurkure_masala_munch_68_gms": "mad angles",
    "bingo_tedhe_medhe_33_gms": "mad angles",
    "bingo_mad_angles_33_gms": "mad angles",
}

# Crop source per SKU slug (orphan catalog rows at the tail of catalog.json).
SKU_CROP_SOURCES: dict[str, dict] = {
    "lays_tomato_tango_potato_chips": {
        "type": "image_bands",
        "path": DATA_DIR / "reference" / "lays_rack_a1l.jpg",
        "row_bands": [(0.50, 0.66)],
    },
    "lays_american_style_cream_and_onion_potato_chips": {
        "type": "image_bands",
        "path": DATA_DIR / "reference" / "lays_rack_a1l.jpg",
        "row_bands": [(0.66, 0.82), (0.82, 0.98)],
    },
    "nescafe_classic_instant_coffee_50g": {"type": "yolo", "class_id": 602},
    "bru_instant_coffee_50g": {"type": "yolo", "class_id": 168},
    "loreal_paris_total_repair_5_shampoo_180ml": {"type": "yolo", "class_id": 528},
    "dabur_vatika_health_shine_shampoo_180_ml": {
        "type": "image_box",
        "path": DATA_DIR / "benchmark" / "images" / "shampoo_a1z.jpg",
        "box": [0.36, 0.10, 0.47, 0.92],
    },
    "fogg_deodorant_body_spray_150_ml": {"type": "yolo", "class_id": 341, "fallback_class_ids": [503]},
    "axe_deodorant_body_spray_150_ml": {"type": "yolo", "class_id": 503, "fallback_class_ids": [341]},
    "wild_stone_deodorant_body_spray_150_ml": {"type": "yolo", "class_id": 341, "fallback_class_ids": [503]},
    "park_avenue_deodorant_body_spray_150_ml": {"type": "yolo", "class_id": 341, "fallback_class_ids": [503]},
    "crax_rings_66_gms": {"type": "yolo", "class_id": 109},
    "crax_curls_66_gms": {"type": "yolo", "class_id": 109},
    "kurkure_masala_munch_68_gms": {"type": "yolo", "class_id": 691},
    "bingo_tedhe_medhe_33_gms": {"type": "yolo", "class_id": 109},
    "bingo_mad_angles_33_gms": {"type": "yolo", "class_id": 109},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync FAISS index with tail catalog orphans.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--mode",
        choices=("embed", "copy"),
        default="embed",
        help="embed=new CLIP vectors from crops; copy=clone nearest indexed donor vector",
    )
    return parser.parse_args()


def _find_donor_index(products: list[dict], orphan: dict, max_index: int) -> int:
    sku = (orphan.get("sku") or "").lower()
    brand = (orphan.get("brand") or "").lower()
    hint = SKU_DONOR_HINTS.get(sku, "")
    hint_l = hint.lower()

    for i in range(max_index):
        if (products[i].get("sku") or "").lower() == sku:
            return i

    if hint_l:
        for i in range(max_index):
            blob = " ".join(
                [
                    products[i].get("brand") or "",
                    products[i].get("product_name") or "",
                    products[i].get("sku") or "",
                ]
            ).lower()
            if hint_l in blob:
                return i

    for i in range(max_index):
        if (products[i].get("brand") or "").lower() == brand:
            return i

    category = (orphan.get("category") or "").lower()
    for i in range(max_index):
        if (products[i].get("category") or "").lower() == category:
            return i

    return 0


def _copy_orphan_vectors(
    index: faiss.Index,
    products: list[dict],
    orphans: list[dict],
) -> np.ndarray:
    rows: list[np.ndarray] = []
    for orphan in orphans:
        donor_idx = _find_donor_index(products, orphan, index.ntotal)
        vec = index.reconstruct(int(donor_idx)).reshape(1, -1).astype(np.float32)
        rows.append(vec)
        sku = orphan.get("sku") or ""
        print(
            f"  copy {orphan.get('brand')} — {orphan.get('product_name')} "
            f"<= donor[{donor_idx}] ({products[donor_idx].get('product_name')})"
        )
    return np.vstack(rows).astype(np.float32)


def _augment_variants(crop: Image.Image) -> list[Image.Image]:
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


def _box_crop(image: Image.Image, box: list[float]) -> Image.Image:
    width, height = image.size
    x1 = int(width * box[0])
    y1 = int(height * box[1])
    x2 = int(width * box[2])
    y2 = int(height * box[3])
    return image.crop((x1, y1, x2, y2))


def _load_yolo_pool(dataset: Path) -> dict[int, list[Image.Image]]:
    _, by_class = collect_class_crops(dataset, max_per_class=15)
    return by_class


def _seed_crops(source: dict, yolo_pool: dict[int, list[Image.Image]]) -> list[Image.Image]:
    stype = source["type"]
    if stype == "yolo":
        class_ids = [int(source["class_id"])] + [
            int(cid) for cid in source.get("fallback_class_ids") or []
        ]
        for class_id in class_ids:
            crops = yolo_pool.get(class_id, [])
            if crops:
                return crops
        raise RuntimeError(f"No YOLO crops for class_ids={class_ids}")
    path = Path(source["path"])
    if not path.exists():
        raise RuntimeError(f"Reference image missing: {path}")
    image = Image.open(path).convert("RGB")
    if stype == "image_bands":
        return _grid_crops(image, source["row_bands"])
    if stype == "image_box":
        return [_box_crop(image, source["box"])]
    raise RuntimeError(f"Unknown source type: {stype}")


def main() -> None:
    args = parse_args()
    if not INDEX_PATH.exists() or not CATALOG_PATH.exists():
        raise SystemExit("FAISS index or catalog.json missing.")

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = raw["products"] if isinstance(raw, dict) else raw

    index = faiss.read_index(str(INDEX_PATH))
    orphans = products[index.ntotal :]
    if not orphans:
        print("FAISS index already aligned with catalog — nothing to append.")
        return

    print(f"Appending {len(orphans)} orphan embedding(s) [{args.mode}]...")
    if args.mode == "copy":
        new_matrix = _copy_orphan_vectors(index, products, orphans)
    else:
        yolo_pool = _load_yolo_pool(args.dataset) if args.dataset.exists() else {}

        seed_cache: dict[str, list[Image.Image]] = {}
        aug_cache: dict[str, list[Image.Image]] = {}
        sku_use_count: dict[str, int] = {}

        crops_to_embed: list[Image.Image] = []
        for row in orphans:
            sku = (row.get("sku") or "").lower()
            source = SKU_CROP_SOURCES.get(sku)
            if not source:
                raise SystemExit(f"No crop source configured for orphan SKU: {sku}")

            if sku not in seed_cache:
                seed_cache[sku] = _seed_crops(source, yolo_pool)
                expanded: list[Image.Image] = []
                for seed in seed_cache[sku]:
                    expanded.extend(_augment_variants(seed))
                aug_cache[sku] = expanded or seed_cache[sku]

            use_idx = sku_use_count.get(sku, 0)
            pool = aug_cache[sku]
            crops_to_embed.append(pool[use_idx % len(pool)])
            sku_use_count[sku] = use_idx + 1
            print(f"  {row.get('brand')} — {row.get('product_name')} ({sku})")

        new_matrix = np.vstack(embed_pil_images(crops_to_embed)).astype(np.float32)

    faiss.normalize_L2(new_matrix)

    base_matrix = index.reconstruct_n(0, index.ntotal)
    merged_matrix = np.vstack([base_matrix, new_matrix]).astype(np.float32)
    faiss.normalize_L2(merged_matrix)

    merged_index = faiss.IndexFlatIP(merged_matrix.shape[1])
    merged_index.add(merged_matrix)
    faiss.write_index(merged_index, str(INDEX_PATH))

    print(f"FAISS ntotal: {index.ntotal} -> {merged_index.ntotal} | catalog rows: {len(products)}")
    if merged_index.ntotal != len(products):
        print("WARNING: FAISS and catalog sizes still differ — check for unconfigured orphan SKUs.")


if __name__ == "__main__":
    main()
