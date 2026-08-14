"""Build FAISS / learned-SKU embeddings from Grocer-Help labeled crops (Phase 2B).

Covers all 647 SKU classes across Aislix categories (tea, shampoo, snacks, dairy, etc.).

Usage::

    py scripts/build_grocer_help_embeddings.py --source "D:\\Grocer-Help"
    py scripts/build_grocer_help_embeddings.py --source "D:\\Grocer-Help" --crops-per-sku 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build SKU embeddings from Grocer-Help crops (all categories).")
    parser.add_argument("--source", type=Path, default=Path(r"D:\Grocer-Help"))
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE_DIR / "data" / "grocer_help" / "embeddings.json",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max unique SKUs (0 = all classes in dataset)")
    parser.add_argument("--crops-per-sku", type=int, default=3, help="Crops per class (averaged into one embedding)")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--stats-out",
        type=Path,
        default=BASE_DIR / "data" / "grocer_help" / "embeddings_by_category.json",
    )
    return parser.parse_args()


def _load_class_names(source: Path) -> list[str]:
    import yaml

    raw = yaml.safe_load((source / "data.yaml").read_text(encoding="utf-8"))
    names = raw.get("names") or []
    if isinstance(names, dict):
        return [names[k] for k in sorted(names, key=lambda x: int(x))]
    return list(names)


def _yolo_to_xyxy(line: str, w: int, h: int) -> tuple[int, int, int, int] | None:
    parts = line.strip().split()
    if len(parts) != 5:
        return None
    _, cx, cy, bw, bh = map(float, parts)
    x1 = int(max(0, (cx - bw / 2) * w))
    y1 = int(max(0, (cy - bh / 2) * h))
    x2 = int(min(w, (cx + bw / 2) * w))
    y2 = int(min(h, (cy + bh / 2) * h))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _collect_crops(
    source: Path,
    class_names: list[str],
    limit: int,
    crops_per_sku: int,
) -> dict[str, list[Image.Image]]:
    """Return class_name -> list of PIL crops (up to crops_per_sku)."""
    train_images = source / "train" / "images"
    train_labels = source / "train" / "labels"
    by_class: dict[str, list[Image.Image]] = {}

    for image_path in sorted(train_images.iterdir()):
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        label_path = train_labels / f"{image_path.stem}.txt"
        if not label_path.exists():
            continue
        bgr = cv2.imread(str(image_path))
        if bgr is None:
            continue
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            class_id = int(parts[0])
            brand = class_names[class_id] if class_id < len(class_names) else str(class_id)
            if len(by_class.get(brand, [])) >= crops_per_sku:
                continue
            box = _yolo_to_xyxy(line, w, h)
            if not box:
                continue
            x1, y1, x2, y2 = box
            crop = Image.fromarray(rgb[y1:y2, x1:x2])
            by_class.setdefault(brand, []).append(crop)

        if limit and len(by_class) >= limit:
            break

    return {k: v for k, v in by_class.items() if v}


def _mean_embedding(vectors: list[np.ndarray]) -> np.ndarray:
    stack = np.vstack([np.asarray(v, dtype=np.float32) for v in vectors])
    mean = stack.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm > 0:
        mean = mean / norm
    return mean.astype(np.float32)


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not (source / "train" / "images").is_dir():
        raise SystemExit(f"Missing train split under {source}")

    from app.catalog import slug_to_metadata
    from app.clip_embeddings import embed_pil_images
    from app.learned_catalog import metadata_to_sku
    from app.sku_category_map import map_class_to_aislix_category

    class_names = _load_class_names(source)
    crop_map = _collect_crops(source, class_names, args.limit, args.crops_per_sku)
    if not crop_map:
        raise SystemExit("No crops collected.")

    records: list[dict] = []
    category_counts: Counter[str] = Counter()

    brands = sorted(crop_map.keys())
    for start in range(0, len(brands), args.batch_size):
        batch_brands = brands[start : start + args.batch_size]
        flat_images: list[Image.Image] = []
        flat_brand_index: list[tuple[str, int]] = []
        for brand in batch_brands:
            for idx, img in enumerate(crop_map[brand]):
                flat_images.append(img)
                flat_brand_index.append((brand, idx))

        embeddings = embed_pil_images(flat_images)
        per_brand: dict[str, list[np.ndarray]] = {}
        for (brand, _idx), vec in zip(flat_brand_index, embeddings):
            per_brand.setdefault(brand, []).append(vec)

        for brand in batch_brands:
            vecs = per_brand.get(brand) or []
            if not vecs:
                continue
            slug = brand.lower().replace(" ", "_").replace("-", "_")
            meta = slug_to_metadata(slug)
            if meta.get("brand") and meta["brand"].lower() not in slug:
                meta["brand"] = brand.replace("_", " ")
            else:
                meta["brand"] = brand.replace("_", " ")
            meta["product_name"] = meta.get("product_name") or meta["brand"]
            cat_info = map_class_to_aislix_category(brand)
            meta["category"] = cat_info["category"]
            sku = metadata_to_sku(meta["brand"], meta["product_name"], meta.get("variant") or "")
            category_counts[meta["category"]] += 1
            records.append({
                "sku": sku,
                "brand": meta["brand"],
                "product_name": meta["product_name"],
                "variant": meta.get("variant") or "",
                "category": meta["category"],
                "category_id": cat_info["category_id"],
                "sub_category_id": cat_info["sub_category_id"],
                "embedding": _mean_embedding(vecs).tolist(),
                "source": "grocer_help",
                "source_scan_id": "grocer_help_phase2b",
                "crops_averaged": len(vecs),
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")

    stats = {
        "total_skus": len(records),
        "by_category": dict(category_counts.most_common()),
    }
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"Wrote {len(records)} SKU embeddings to {args.output}")
    print(f"Category breakdown -> {args.stats_out}")
    for cat, n in category_counts.most_common(12):
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
