#!/usr/bin/env python3
"""Build FAISS index + catalog.json from a YOLO dataset."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import faiss
import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import save_catalog, slug_to_metadata  # noqa: E402
from app.clip_embeddings import embed_pil_images  # noqa: E402

DEFAULT_DATASET = Path(r"D:\combinedDataset.v3-dataset_master_file.yolov8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--max-per-class", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser.parse_args()


def load_class_names(dataset_dir: Path) -> list[str]:
    with open(dataset_dir / "data.yaml", encoding="utf-8") as f:
        return list(yaml.safe_load(f)["names"])


def resolve_image(images_dir: Path, stem: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = images_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def yolo_crops(image_path: Path, label_path: Path, class_id: int) -> list[Image.Image]:
    image = cv2.imread(str(image_path))
    if image is None:
        return []
    h, w = image.shape[:2]
    crops: list[tuple[int, Image.Image]] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        cid = int(float(parts[0]))
        if cid != class_id:
            continue
        _, xc, yc, bw, bh = map(float, parts)
        x1, y1 = max(0, int((xc - bw / 2) * w)), max(0, int((yc - bh / 2) * h))
        x2, y2 = min(w, int((xc + bw / 2) * w)), min(h, int((yc + bh / 2) * h))
        area = max(0, x2 - x1) * max(0, y2 - y1)
        if area <= 0:
            continue
        crop = image[y1:y2, x1:x2]
        if crop.size:
            crops.append((area, Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))))
    crops.sort(key=lambda item: item[0], reverse=True)
    return [img for _, img in crops]


def main() -> None:
    args = parse_args()
    dataset_dir = args.dataset
    if not dataset_dir.exists():
        raise SystemExit(f"Dataset not found: {dataset_dir}")

    class_names = load_class_names(dataset_dir)
    images_dir = dataset_dir / "train" / "images"
    labels_dir = dataset_dir / "train" / "labels"
    by_class: dict[int, list[Image.Image]] = defaultdict(list)

    for label_file in labels_dir.glob("*.txt"):
        image_path = resolve_image(images_dir, label_file.stem)
        if not image_path:
            continue
        class_ids = set()
        for line in label_file.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) == 5:
                class_ids.add(int(float(parts[0])))
        for cid in class_ids:
            if len(by_class[cid]) >= args.max_per_class:
                continue
            for crop in yolo_crops(image_path, label_file, cid):
                if len(by_class[cid]) >= args.max_per_class:
                    break
                by_class[cid].append(crop)

    print(f"Collected crops for {len(by_class)} / {len(class_names)} classes")

    catalog_entries: list[dict] = []
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

    catalog_entries = crop_meta

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(data_dir / "faiss.index"))
    save_catalog(catalog_entries)
    print(f"Saved {len(catalog_entries)} embeddings + catalog to {data_dir}")


if __name__ == "__main__":
    main()
