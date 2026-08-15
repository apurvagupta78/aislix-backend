"""Export labeled facing crops for PaddleOCR recognition fine-tuning."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from app.ocr_reader import load_facing_image


def _resolve_box(facing: dict, width: int, height: int) -> list[int]:
    from app.accuracy_benchmark import resolve_facing_box

    return resolve_facing_box(facing, width, height)


def export_from_manifest(
    manifest_path: Path,
    out_dir: Path,
    *,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for case in manifest.get("cases", []):
        image_path = manifest_path.parent / case["image"]
        if not image_path.exists():
            continue
        source = cv2.imread(str(image_path))
        if source is None:
            continue
        h, w = source.shape[:2]
        case_id = case["id"]
        for facing in case.get("facings") or []:
            label = facing.get("ocr_label") or facing.get("product_name") or ""
            brand = facing.get("brand") or ""
            if brand and brand.lower() not in label.lower():
                label = f"{brand} {label}".strip()
            if len(label) < 3:
                continue
            x1, y1, x2, y2 = _resolve_box(facing, w, h)
            record = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
            crop = load_facing_image(record, source)
            fid = facing.get("id") or f"{x1}_{y1}"
            filename = f"{case_id}_{fid}.jpg"
            crop.save(images_dir / filename, quality=95)
            rows.append(
                {
                    "file": filename,
                    "text": label,
                    "case_id": case_id,
                    "sub_category": case.get("sub_category") or "",
                }
            )

    rng = random.Random(seed)
    rng.shuffle(rows)
    val_count = max(1, int(len(rows) * val_ratio)) if len(rows) >= 8 else max(0, len(rows) // 5)
    for idx, row in enumerate(rows):
        row["split"] = "val" if idx < val_count else "train"

    labels_path = out_dir / "labels.csv"
    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "text", "case_id", "sub_category", "split"])
        writer.writeheader()
        writer.writerows(rows)

    for split in ("train", "val"):
        split_rows = [row for row in rows if row["split"] == split]
        split_path = out_dir / f"labels_{split}.txt"
        with split_path.open("w", encoding="utf-8") as handle:
            for row in split_rows:
                handle.write(f"images/{row['file']}\t{row['text']}\n")

    readme = out_dir / "README.md"
    readme.write_text(
        "# OCR fine-tune dataset\n\n"
        "1. Add facings with `ocr_label` in `data/benchmark/manifest.json` (all categories).\n"
        "2. Re-run: `py scripts/prepare_ocr_finetune_dataset.py`\n"
        "3. Train PaddleOCR rec on `labels_train.txt`, validate on `labels_val.txt`.\n"
        "4. Deploy: `OCR_PADDLE_REC_MODEL_DIR` + `OCR_PADDLE_REC_MODEL=custom` on Railway.\n\n"
        "See `docs/ACCURACY_IMPROVEMENT.md` for the full cross-category loop.\n",
        encoding="utf-8",
    )
    train_n = sum(1 for row in rows if row["split"] == "train")
    val_n = sum(1 for row in rows if row["split"] == "val")
    return {
        "exported": len(rows),
        "train": train_n,
        "val": val_n,
        "out_dir": str(out_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OCR fine-tuning crops from benchmark manifest.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "benchmark" / "manifest.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "ocr_finetune",
    )
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    stats = export_from_manifest(args.manifest, args.out, val_ratio=args.val_ratio, seed=args.seed)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
