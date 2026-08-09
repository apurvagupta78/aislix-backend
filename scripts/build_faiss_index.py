#!/usr/bin/env python3
"""Build FAISS index + catalog.json from a YOLO dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import faiss
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import save_catalog, slug_to_metadata  # noqa: E402
from app.clip_embeddings import embed_pil_images, using_retailklip  # noqa: E402
from scripts.yolo_dataset import DEFAULT_DATASET, collect_class_crops  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--max-per-class", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    class_names, by_class = collect_class_crops(args.dataset, max_per_class=args.max_per_class)
    if not by_class:
        raise SystemExit(f"No crops found in dataset: {args.dataset}")

    embedder = "RetailKLIP" if using_retailklip() else "OpenCLIP"
    print(f"Collected crops for {len(by_class)} / {len(class_names)} classes (embedder={embedder})")

    all_crops: list[Image.Image] = []
    crop_meta: list[dict] = []

    for class_id in sorted(by_class.keys()):
        slug = class_names[class_id]
        meta = slug_to_metadata(slug)
        for crop in by_class[class_id]:
            all_crops.append(crop)
            crop_meta.append({"class_id": class_id, **meta})

    print(f"Embedding {len(all_crops)} reference crops...")
    embeddings: list[np.ndarray] = []
    for start in range(0, len(all_crops), args.batch_size):
        batch = all_crops[start : start + args.batch_size]
        embs = embed_pil_images(batch)
        embeddings.extend(embs)

    matrix = np.vstack(embeddings).astype(np.float32)
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(data_dir / "faiss.index"))
    save_catalog(crop_meta)
    print(f"Saved {len(crop_meta)} embeddings + catalog to {data_dir}")


if __name__ == "__main__":
    main()
