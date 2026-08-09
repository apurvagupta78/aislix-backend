"""Shared YOLO crop extraction for FAISS build and RetailKLIP training."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import yaml
from PIL import Image

DEFAULT_DATASET = Path(r"D:\combinedDataset.v3-dataset_master_file.yolov8")


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
    found: list[tuple[int, Image.Image]] = []
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
            found.append((area, Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))))
    found.sort(key=lambda item: item[0], reverse=True)
    return [img for _, img in found]


def collect_class_crops(
    dataset_dir: Path,
    *,
    max_per_class: int = 15,
    max_classes: int | None = None,
) -> tuple[list[str], dict[int, list[Image.Image]]]:
    """Return class names and {class_id: [PIL crops]}."""
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_dir}")

    class_names = load_class_names(dataset_dir)
    images_dir = dataset_dir / "train" / "images"
    labels_dir = dataset_dir / "train" / "labels"
    by_class: dict[int, list[Image.Image]] = defaultdict(list)

    for label_file in labels_dir.glob("*.txt"):
        image_path = resolve_image(images_dir, label_file.stem)
        if not image_path:
            continue
        class_ids: set[int] = set()
        for line in label_file.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) == 5:
                class_ids.add(int(float(parts[0])))
        for cid in class_ids:
            if max_classes is not None and len(by_class) >= max_classes and cid not in by_class:
                continue
            if len(by_class[cid]) >= max_per_class:
                continue
            for crop in yolo_crops(image_path, label_file, cid):
                if len(by_class[cid]) >= max_per_class:
                    break
                by_class[cid].append(crop)

    return class_names, dict(by_class)
