"""Export labeled facing crops for PaddleOCR recognition fine-tuning."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from app.ocr_reader import load_facing_image


def _resolve_box(facing: dict, width: int, height: int) -> list[int]:
    box = facing.get("box") or [0, 0, 0, 0]
    if len(box) != 4:
        return [0, 0, 0, 0]
    if all(isinstance(v, (int, float)) and 0 <= float(v) <= 1 for v in box):
        return [
            int(float(box[0]) * width),
            int(float(box[1]) * height),
            int(float(box[2]) * width),
            int(float(box[3]) * height),
        ]
    return [int(box[0]), int(box[1]), int(box[2]), int(box[3])]


def export_from_manifest(manifest_path: Path, out_dir: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_path = out_dir / "labels.csv"
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
            rows.append({"file": filename, "text": label, "case_id": case_id})

    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "text", "case_id"])
        writer.writeheader()
        writer.writerows(rows)

    readme = out_dir / "README.md"
    readme.write_text(
        "# OCR fine-tune dataset\n\n"
        "1. Add more facings with `ocr_label` in `data/benchmark/manifest.json`.\n"
        "2. Re-run: `py scripts/prepare_ocr_finetune_dataset.py`\n"
        "3. Fine-tune PaddleOCR rec model (see `docs/OCR_FINETUNE.md`).\n"
        "4. Deploy custom rec weights via `OCR_PADDLE_REC_MODEL_DIR` on Railway.\n",
        encoding="utf-8",
    )
    return {"exported": len(rows), "out_dir": str(out_dir)}


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
    args = parser.parse_args()
    stats = export_from_manifest(args.manifest, args.out)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
