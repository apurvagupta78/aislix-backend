#!/usr/bin/env python3
"""Evaluate shelf facing detection on the held-out benchmark set."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BENCHMARK_DIR = ROOT / "data" / "benchmark"
MANIFEST_PATH = BENCHMARK_DIR / "manifest.json"
REPORTS_DIR = BENCHMARK_DIR / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run shelf detection benchmark.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="Path to benchmark manifest.json",
    )
    parser.add_argument(
        "--mode",
        choices=("standard", "sahi"),
        default=None,
        help="Detection mode (default: DETECTION_MODE env or standard)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run both standard and SAHI and print delta",
    )
    parser.add_argument(
        "--iou",
        type=float,
        default=0.5,
        help="IoU threshold for box matching",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _ground_truth_boxes(case: dict) -> list:
    boxes = []
    for facing in case.get("facings") or []:
        box = facing.get("box")
        if box and len(box) == 4:
            boxes.append(box)
    return boxes


def _evaluate_case(image_path: Path, case: dict, *, mode: str, iou: float) -> dict:
    from app.benchmark_metrics import match_boxes
    from app.detector import load_image_bytes
    from app.pipeline import _detect_adaptive_boxes

    os.environ["DETECTION_MODE"] = mode
    image = load_image_bytes(image_path.read_bytes())
    boxes, shelf_mode, det_stats = _detect_adaptive_boxes(image)
    predicted = [b.tolist() if hasattr(b, "tolist") else list(b) for b in boxes]

    gt_boxes = _ground_truth_boxes(case)
    expected_count = int(case.get("expected_facing_count") or len(gt_boxes) or 0)

    result = {
        "id": case["id"],
        "mode": mode,
        "image": str(image_path),
        "shelf_mode": shelf_mode,
        "predicted_count": len(predicted),
        "expected_facing_count": expected_count,
        "count_error": abs(len(predicted) - expected_count) if expected_count else None,
        "detection_stats": det_stats,
    }

    if gt_boxes:
        metrics = match_boxes(predicted, gt_boxes, iou_threshold=iou)
        result.update(metrics)
    elif expected_count:
        tp = min(len(predicted), expected_count)
        result["true_positives"] = tp
        result["ground_truth_count"] = expected_count
        result["recall"] = round(tp / expected_count, 4)
        result["precision"] = round(tp / max(len(predicted), 1), 4)
        result["false_negatives"] = max(expected_count - tp, 0)
        result["false_positives"] = max(len(predicted) - tp, 0)

    return result


def run_benchmark(manifest: dict, *, mode: str, iou: float) -> dict:
    case_results = []
    skipped = []

    for case in manifest.get("cases") or []:
        rel = case.get("image") or ""
        image_path = (manifest.get("_base_dir") or BENCHMARK_DIR) / rel
        if not image_path.exists():
            skipped.append({"id": case.get("id"), "reason": f"missing image: {image_path}"})
            continue
        case_results.append(_evaluate_case(image_path, case, mode=mode, iou=iou))

    from app.benchmark_metrics import aggregate_detection_metrics

    summary = aggregate_detection_metrics(case_results) if case_results else {"cases": 0}
    return {
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "iou_threshold": iou,
        "summary": summary,
        "cases": case_results,
        "skipped": skipped,
    }


def _print_report(report: dict) -> None:
    summary = report.get("summary") or {}
    print(f"\n=== Detection benchmark ({report['mode']}) ===")
    print(f"Cases evaluated: {summary.get('cases', 0)}")
    if summary.get("cases", 0) == 0:
        for row in report.get("skipped") or []:
            print(f"  SKIP {row['id']}: {row['reason']}")
        print("\nAdd images under data/benchmark/images/ (see README.md).")
        return

    print(f"Facing recall:    {summary.get('facing_recall', 'n/a')}")
    print(f"Facing precision: {summary.get('facing_precision', 'n/a')}")
    print(f"GT facings: {summary.get('total_ground_truth_facings')}  Pred: {summary.get('total_predicted_facings')}")

    for case in report.get("cases") or []:
        line = (
            f"  {case['id']}: pred={case['predicted_count']} "
            f"expected={case.get('expected_facing_count')} mode={case.get('shelf_mode')}"
        )
        if case.get("recall") is not None:
            line += f" recall={case['recall']} precision={case.get('precision')}"
        if case.get("count_error") is not None:
            line += f" count_err={case['count_error']}"
        print(line)


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.manifest.resolve())
    manifest["_base_dir"] = args.manifest.resolve().parent

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    modes = ["standard", "sahi"] if args.compare else [args.mode or os.getenv("DETECTION_MODE", "standard")]

    reports = []
    for mode in modes:
        report = run_benchmark(manifest, mode=mode, iou=args.iou)
        reports.append(report)
        _print_report(report)
        out = REPORTS_DIR / f"benchmark_{mode}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {out}")

    if len(reports) == 2:
        std = reports[0]["summary"]
        sahi = reports[1]["summary"]
        if std.get("cases") and sahi.get("cases"):
            dr = (sahi.get("facing_recall") or 0) - (std.get("facing_recall") or 0)
            dp = (sahi.get("facing_precision") or 0) - (std.get("facing_precision") or 0)
            print(f"\nSAHI delta — recall: {dr:+.4f}  precision: {dp:+.4f}")


if __name__ == "__main__":
    main()
