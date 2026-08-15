"""End-to-end OCR evaluation on benchmark facing crops."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from app.brand_dictionary import match_from_text, normalize_ocr_text
from app.ocr_reader import load_facing_image, read_packaging_text_result


def _brand_match(expected: str, actual: str) -> bool:
    exp = (expected or "").lower().strip()
    act = (actual or "").lower().strip()
    if not exp:
        return True
    return exp == act or exp in act or act in exp


def _product_match(expected: str, actual: str) -> bool:
    exp = (expected or "").lower().strip()
    act = (actual or "").lower().strip()
    if not exp:
        return True
    if exp in act or act in exp:
        return True
    exp_tokens = set(exp.split())
    act_tokens = set(act.split())
    if not exp_tokens:
        return True
    overlap = len(exp_tokens & act_tokens) / len(exp_tokens)
    return overlap >= 0.5


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


def _evaluate_facing(
    source: np.ndarray,
    facing: dict,
    scan_context: dict | None,
) -> dict:
    h, w = source.shape[:2]
    x1, y1, x2, y2 = _resolve_box(facing, w, h)
    record = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    crop = load_facing_image(record, source)
    result = read_packaging_text_result(crop, scan_context=scan_context, heavy=False)
    if len(result.text.strip()) < 3 or result.confidence < 0.55:
        heavy = read_packaging_text_result(crop, scan_context=scan_context, heavy=True)
        if heavy.score >= result.score or len(heavy.text.strip()) > len(result.text.strip()):
            result = heavy

    normalized = normalize_ocr_text(result.text)
    match = match_from_text(normalized, scan_context=scan_context)
    expected_brand = facing.get("brand") or ""
    expected_product = facing.get("product_name") or ""
    got_brand = (match or {}).get("brand") or ""
    got_product = (match or {}).get("product_name") or ""

    return {
        "id": facing.get("id"),
        "ocr_text": result.text[:120],
        "ocr_confidence": result.confidence,
        "ocr_variant": result.variant,
        "ocr_nonempty": len(result.text.strip()) >= 3,
        "brand_ok": _brand_match(expected_brand, got_brand),
        "product_ok": _product_match(expected_product, got_product),
        "expected_brand": expected_brand,
        "expected_product": expected_product,
        "got_brand": got_brand,
        "got_product": got_product,
    }


def _evaluate_case(case: dict, benchmark_dir: Path) -> dict:
    image_path = benchmark_dir / case["image"]
    if not image_path.exists():
        return {"id": case["id"], "skipped": True, "reason": "image missing"}

    source = cv2.imread(str(image_path))
    if source is None:
        return {"id": case["id"], "skipped": True, "reason": "could not read image"}

    scan_context = {"aislix_category": case.get("category"), "sub_category": case.get("sub_category")}
    facings = case.get("facings") or []
    if not facings:
        return {"id": case["id"], "skipped": True, "reason": "no facing ground truth"}

    rows = [_evaluate_facing(source, facing, scan_context) for facing in facings]
    total = len(rows)
    nonempty = sum(1 for r in rows if r["ocr_nonempty"])
    brand_ok = sum(1 for r in rows if r["brand_ok"])
    product_ok = sum(1 for r in rows if r["product_ok"])

    return {
        "id": case["id"],
        "skipped": False,
        "facings": total,
        "ocr_nonempty_rate": round(100.0 * nonempty / total, 1) if total else 0.0,
        "brand_match_rate": round(100.0 * brand_ok / total, 1) if total else 0.0,
        "product_match_rate": round(100.0 * product_ok / total, 1) if total else 0.0,
        "details": rows,
    }


def run_eval(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_dir = manifest_path.parent
    case_results = [_evaluate_case(case, benchmark_dir) for case in manifest.get("cases", [])]
    evaluated = [c for c in case_results if not c.get("skipped")]
    if not evaluated:
        return {"cases": case_results, "summary": {"evaluated": 0}}

    avg_nonempty = sum(c["ocr_nonempty_rate"] for c in evaluated) / len(evaluated)
    avg_brand = sum(c["brand_match_rate"] for c in evaluated) / len(evaluated)
    avg_product = sum(c["product_match_rate"] for c in evaluated) / len(evaluated)

    return {
        "cases": case_results,
        "summary": {
            "evaluated": len(evaluated),
            "avg_ocr_nonempty_rate": round(avg_nonempty, 1),
            "avg_brand_match_rate": round(avg_brand, 1),
            "avg_product_match_rate": round(avg_product, 1),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate OCR on benchmark facing crops.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "benchmark" / "manifest.json",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = run_eval(args.manifest)
    text = json.dumps(report, indent=2)
    print(text)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        out_dir = args.manifest.parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ocr_eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(text, encoding="utf-8")
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
