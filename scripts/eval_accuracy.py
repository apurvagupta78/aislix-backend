#!/usr/bin/env python3
"""Unified cross-category accuracy evaluation: detection, OCR, recognition, text matching."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from app.accuracy_benchmark import (
    aggregate_cer,
    aggregate_rates,
    brand_match,
    case_scan_context,
    category_key,
    character_error_rate,
    detection_metrics_for_case,
    expected_ocr_label,
    match_predicted_to_ground_truth,
    product_match,
    resolve_facing_box,
)
from app.brand_dictionary import match_from_text, normalize_ocr_text
from app.ocr_reader import load_facing_image, read_packaging_text_result


def _evaluate_ocr_facing(source, facing: dict, scan_context: dict | None) -> dict:
    h, w = source.shape[:2]
    x1, y1, x2, y2 = resolve_facing_box(facing, w, h)
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
    gt_ocr = expected_ocr_label(facing)

    return {
        "id": facing.get("id"),
        "ocr_text": result.text[:160],
        "ocr_confidence": result.confidence,
        "ocr_nonempty": len(result.text.strip()) >= 3,
        "cer": round(character_error_rate(gt_ocr, result.text), 4) if gt_ocr else None,
        "brand_ok": brand_match(expected_brand, got_brand),
        "product_ok": product_match(expected_product, got_product),
        "expected_brand": expected_brand,
        "expected_product": expected_product,
        "got_brand": got_brand,
        "got_product": got_product,
    }


def _evaluate_detection_case(case: dict, benchmark_dir: Path, *, mode: str, iou: float) -> dict:
    from app.detector import load_image_bytes
    from app.pipeline import _detect_adaptive_boxes

    image_path = benchmark_dir / case["image"]
    if not image_path.exists():
        return {"id": case["id"], "skipped": True, "reason": "image missing", "tier": "detection"}

    os.environ["DETECTION_MODE"] = mode
    image = load_image_bytes(image_path.read_bytes())
    boxes, _, _ = _detect_adaptive_boxes(image)
    predicted = [b.tolist() if hasattr(b, "tolist") else list(b) for b in boxes]
    stats = detection_metrics_for_case(predicted, case, iou_threshold=iou)
    return {
        "id": case["id"],
        "category": category_key(case),
        "skipped": False,
        "tier": "detection",
        **stats,
    }


def _evaluate_ocr_case(case: dict, benchmark_dir: Path) -> dict:
    image_path = benchmark_dir / case["image"]
    if not image_path.exists():
        return {"id": case["id"], "skipped": True, "reason": "image missing", "tier": "ocr"}

    source = cv2.imread(str(image_path))
    if source is None:
        return {"id": case["id"], "skipped": True, "reason": "could not read image", "tier": "ocr"}

    facings = case.get("facings") or []
    if not facings:
        return {"id": case["id"], "skipped": True, "reason": "no facing ground truth", "tier": "ocr"}

    ctx = case_scan_context(case)
    rows = [_evaluate_ocr_facing(source, facing, ctx) for facing in facings]
    cer_rows = [r for r in rows if r.get("cer") is not None]
    return {
        "id": case["id"],
        "category": category_key(case),
        "skipped": False,
        "tier": "ocr",
        "facings": len(rows),
        "ocr_nonempty_rate": aggregate_rates(rows, "ocr_nonempty"),
        "brand_match_rate": aggregate_rates(rows, "brand_ok"),
        "product_match_rate": aggregate_rates(rows, "product_ok"),
        "avg_cer_percent": aggregate_cer(cer_rows),
        "details": rows,
    }


def _evaluate_recognition_case(case: dict, benchmark_dir: Path) -> dict:
    from app.pipeline import run_scan_from_bytes
    from app.scan_context import resolve_scan_context

    image_path = benchmark_dir / case["image"]
    if not image_path.exists():
        return {"id": case["id"], "skipped": True, "reason": "image missing", "tier": "recognition"}

    facings = case.get("facings") or []
    if not facings:
        return {"id": case["id"], "skipped": True, "reason": "no facing ground truth", "tier": "recognition"}

    metadata = {
        "category": case.get("category"),
        "sub_category": case.get("sub_category"),
        "location": case.get("location"),
        "export_facings": True,
    }
    result = run_scan_from_bytes(image_path.read_bytes(), scan_id=f"bench-{case['id']}", metadata=metadata)
    predicted = result.get("facings_debug") or []
    source = cv2.imread(str(image_path))
    h, w = source.shape[:2]
    pairs = match_predicted_to_ground_truth(predicted, facings, width=w, height=h)
    return {
        "id": case["id"],
        "category": category_key(case),
        "skipped": False,
        "tier": "recognition",
        "matched_facings": len(pairs),
        "ground_truth_facings": len(facings),
        "brand_match_rate": aggregate_rates(pairs, "brand_ok"),
        "product_match_rate": aggregate_rates(pairs, "product_ok"),
        "sku_match_rate": aggregate_rates(pairs, "sku_ok"),
        "processing_time_ms": (result.get("metrics") or {}).get("processing_time_ms"),
        "details": pairs,
    }


def _evaluate_text_dictionary() -> dict:
    from scripts.benchmark_shelf import ALL_BENCHMARKS, run_ocr_benchmark

    suites: dict[str, dict] = {}
    total_correct = 0
    total = 0
    for name, cases in ALL_BENCHMARKS:
        result = run_ocr_benchmark(cases)
        suites[name] = result
        total_correct += result["correct"]
        total += result["total"]
    return {
        "tier": "text_dictionary",
        "accuracy_percent": round(100.0 * total_correct / max(total, 1), 1),
        "total": total,
        "correct": total_correct,
        "suites": suites,
    }


def _category_summary(case_results: list[dict], metric_key: str) -> dict[str, float]:
    by_cat: dict[str, list[float]] = {}
    for row in case_results:
        if row.get("skipped"):
            continue
        cat = row.get("category") or "general"
        value = row.get(metric_key)
        if value is None:
            continue
        by_cat.setdefault(cat, []).append(float(value))
    return {cat: round(sum(vals) / len(vals), 1) for cat, vals in by_cat.items()}


def run_eval(
    manifest_path: Path,
    *,
    tiers: set[str],
    detection_mode: str,
    iou: float,
    full_scan: bool,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_dir = manifest_path.parent
    cases = manifest.get("cases", [])

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "tiers": sorted(tiers),
    }

    if "detection" in tiers:
        det_results = [
            _evaluate_detection_case(case, benchmark_dir, mode=detection_mode, iou=iou) for case in cases
        ]
        evaluated = [c for c in det_results if not c.get("skipped")]
        report["detection"] = {
            "cases": det_results,
            "summary": {
                "evaluated": len(evaluated),
                "avg_recall": round(
                    sum(c["recall"] for c in evaluated) / max(len(evaluated), 1), 4
                ),
                "avg_count_error": round(
                    sum(c["count_error"] for c in evaluated) / max(len(evaluated), 1), 2
                ),
                "by_category": _category_summary(evaluated, "recall"),
            },
        }

    if "ocr" in tiers:
        ocr_results = [_evaluate_ocr_case(case, benchmark_dir) for case in cases]
        evaluated = [c for c in ocr_results if not c.get("skipped")]
        report["ocr"] = {
            "cases": ocr_results,
            "summary": {
                "evaluated": len(evaluated),
                "avg_product_match_rate": round(
                    sum(c["product_match_rate"] for c in evaluated) / max(len(evaluated), 1), 1
                ),
                "avg_cer_percent": round(
                    sum(c["avg_cer_percent"] for c in evaluated) / max(len(evaluated), 1), 1
                ),
                "by_category": _category_summary(evaluated, "product_match_rate"),
            },
        }

    if "recognition" in tiers and full_scan:
        rec_results = [_evaluate_recognition_case(case, benchmark_dir) for case in cases]
        evaluated = [c for c in rec_results if not c.get("skipped")]
        report["recognition"] = {
            "cases": rec_results,
            "summary": {
                "evaluated": len(evaluated),
                "avg_product_match_rate": round(
                    sum(c["product_match_rate"] for c in evaluated) / max(len(evaluated), 1), 1
                ),
                "avg_sku_match_rate": round(
                    sum(c["sku_match_rate"] for c in evaluated) / max(len(evaluated), 1), 1
                ),
                "by_category": _category_summary(evaluated, "product_match_rate"),
            },
        }

    if "text" in tiers:
        report["text_dictionary"] = _evaluate_text_dictionary()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Aislix accuracy evaluation.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "benchmark" / "manifest.json")
    parser.add_argument(
        "--tier",
        choices=("detection", "ocr", "recognition", "text", "all"),
        default="all",
    )
    parser.add_argument("--detection-mode", choices=("standard", "sahi"), default=os.getenv("DETECTION_MODE", "standard"))
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Run end-to-end pipeline for recognition tier (slow; needs GPU/OCR)",
    )
    parser.add_argument("--min-product-accuracy", type=float, default=95.0)
    parser.add_argument("--min-detection-recall", type=float, default=0.85)
    parser.add_argument("--min-text-accuracy", type=float, default=95.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.tier == "all":
        tiers = {"detection", "ocr", "text"}
        if args.full_scan:
            tiers.add("recognition")
    else:
        tiers = {args.tier}

    report = run_eval(
        args.manifest,
        tiers=tiers,
        detection_mode=args.detection_mode,
        iou=args.iou,
        full_scan=args.full_scan,
    )
    text = json.dumps(report, indent=2)
    print(text)

    failed = False
    ocr_summary = (report.get("ocr") or {}).get("summary") or {}
    if ocr_summary.get("evaluated") and ocr_summary.get("avg_product_match_rate", 0) < args.min_product_accuracy:
        print(
            f"\nFAIL: OCR product match {ocr_summary['avg_product_match_rate']}% "
            f"< {args.min_product_accuracy}%"
        )
        failed = True
    det_summary = (report.get("detection") or {}).get("summary") or {}
    if det_summary.get("evaluated") and det_summary.get("avg_recall", 0) < args.min_detection_recall:
        print(
            f"\nFAIL: Detection recall {det_summary['avg_recall']} "
            f"< {args.min_detection_recall}"
        )
        failed = True
    text_summary = report.get("text_dictionary") or {}
    if text_summary.get("accuracy_percent", 100) < args.min_text_accuracy:
        print(
            f"\nFAIL: Text dictionary {text_summary['accuracy_percent']}% "
            f"< {args.min_text_accuracy}%"
        )
        failed = True

    out_path = args.out
    if out_path is None:
        out_dir = args.manifest.parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"accuracy_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(text, encoding="utf-8")
    print(f"\nWrote {out_path}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
