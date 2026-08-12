"""Fine-tune the single-class shelf facing detector (best.pt).

The 857-class Roboflow dataset under combinedDataset is catalog-style (one product
per 720x720 image) and is used for FAISS / RetailKLIP — not for YOLO shelf detection.

This script fine-tunes the deployed 1-class ``object`` detector on **shelf photos**
where each bounding box is one physical facing (bottle, box, pouch, etc.).

Dataset layout (YOLO format)::

    data/shelf_detector/
      data.yaml
      train/images/*.jpg
      train/labels/*.txt   # class 0 only — one row per facing
      valid/images/*.jpg
      valid/labels/*.txt

Label every facing with class ``0``. Export from Roboflow as YOLOv8, then either:
  - point --dataset at the export folder (must contain data.yaml), or
  - run scripts/prepare_shelf_dataset.py to collapse a multi-class export to class 0.

Examples::

    python scripts/train_yolo_shelf.py --dataset data/shelf_detector --epochs 80
    python scripts/train_yolo_shelf.py --dataset D:\\roboflow\\shelf-rows-v1 --epochs 50 --resume best.pt

After training, evaluate on held-out shelf photos, then copy the best checkpoint::

    copy runs\\shelf_detector\\weights\\best.pt best.pt

Commit and push best.pt to deploy on Railway.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASE_MODEL = BASE_DIR / "best.pt"
DEFAULT_PROJECT = BASE_DIR / "runs" / "shelf_detector"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO shelf facing detector.")
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to YOLO dataset folder containing data.yaml",
    )
    parser.add_argument(
        "--base-model",
        type=Path,
        default=DEFAULT_BASE_MODEL,
        help="Starting checkpoint (default: repo best.pt)",
    )
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=1280, help="Training image size (1280 helps edge bottles)")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="", help="cuda device id, cpu, or empty for auto")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--name", default="train")
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument(
        "--data-yaml",
        default="data.yaml",
        help="Dataset yaml filename (default: data.yaml; use data.fixed.yaml for SKU-110K)",
    )
    parser.add_argument(
        "--copy-to-repo",
        action="store_true",
        help="Copy best weights to ./best.pt when training finishes",
    )
    return parser.parse_args()


def _resolve_dataset_path(dataset_dir: Path, path: str) -> str:
    """Resolve Roboflow-style relative paths (including erroneous ../ prefixes)."""
    raw = Path(path)
    if raw.is_absolute():
        return str(raw)

    candidates = [
        (dataset_dir / raw).resolve(),
        (dataset_dir / raw.name).resolve(),
        (dataset_dir / str(raw).lstrip("./")).resolve(),
    ]
    parts = raw.parts
    if parts and parts[0] == "..":
        trimmed = Path(*parts[1:])
        candidates.append((dataset_dir / trimmed).resolve())

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return str((dataset_dir / raw).resolve())


def _ensure_single_class_data_yaml(dataset_dir: Path, data_yaml_name: str = "data.yaml") -> Path:
    """Write a single-class data.yaml if the export still lists SKU names."""
    import yaml

    source = dataset_dir / data_yaml_name
    if not source.exists():
        fixed = dataset_dir / "data.fixed.yaml"
        if fixed.exists():
            return fixed
        raise FileNotFoundError(f"Missing data.yaml in {dataset_dir}")

    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    names = raw.get("names")
    patched = dict(raw)
    if names != ["object"] and names != {0: "object"}:
        patched["nc"] = 1
        patched["names"] = ["object"]

    for split in ("train", "val", "valid", "test"):
        if split in patched and isinstance(patched[split], str):
            patched[split] = _resolve_dataset_path(dataset_dir, patched[split])

    if "val" not in patched and "valid" in patched:
        patched["val"] = patched["valid"]

    out = dataset_dir / "data.single_class.yaml"
    out.write_text(yaml.safe_dump(patched, sort_keys=False), encoding="utf-8")
    if names == ["object"] or names == {0: "object"}:
        print(f"Wrote path-fixed config: {out}")
    else:
        print(f"Wrote single-class config: {out}")
    return out


def train(args: argparse.Namespace) -> Path:
    from ultralytics import YOLO

    dataset_dir = args.dataset.resolve()
    data_yaml = _ensure_single_class_data_yaml(dataset_dir, data_yaml_name=args.data_yaml)
    base_model = args.base_model.resolve()
    if not base_model.exists():
        raise FileNotFoundError(f"Base model not found: {base_model}")

    model = YOLO(str(base_model))
    results = model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device or None,
        project=str(args.project),
        name=args.name,
        patience=args.patience,
        exist_ok=True,
        pretrained=True,
        optimizer="AdamW",
        cos_lr=True,
        close_mosaic=10,
        # Shelf-specific augmentations — edge bottles, partial occlusion, glare, dark packs
        hsv_h=0.015,
        hsv_s=0.6,
        hsv_v=0.5,
        degrees=2.0,
        translate=0.08,
        scale=0.35,
        shear=0.0,
        perspective=0.0005,
        flipud=0.0,
        fliplr=0.5,
        mosaic=0.8,
        mixup=0.05,
        copy_paste=0.05,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        best = Path(results.save_dir) / "weights" / "last.pt"
    print(f"Training complete. Best weights: {best}")

    if args.copy_to_repo:
        dest = BASE_DIR / "best.pt"
        shutil.copy2(best, dest)
        print(f"Copied to {dest}")
    return best


def main() -> None:
    args = parse_args()
    train(args)


if __name__ == "__main__":
    main()
