#!/usr/bin/env python3
"""Export low-confidence facings from scan dumps into a labeling queue."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _needs_label(facing: dict, *, ocr_threshold: float, confidence_threshold: float) -> bool:
    brand = (facing.get("brand") or "").lower()
    product = (facing.get("product_name") or "").lower()
    if brand in {"", "unknown"} or product in {"", "unknown", "unidentified sku"}:
        return True
    ocr_conf = float(facing.get("ocr_confidence") or 0)
    conf = float(facing.get("confidence") or 0)
    if ocr_conf and ocr_conf < ocr_threshold:
        return True
    if conf < confidence_threshold:
        return True
    pack = (facing.get("pack_text") or "").strip()
    if len(pack) < 3:
        return True
    return False


def export_queue(
    scan_path: Path,
    *,
    ocr_threshold: float,
    confidence_threshold: float,
) -> dict:
    payload = json.loads(scan_path.read_text(encoding="utf-8"))
    facings = payload.get("facings") or []
    queue = []
    for idx, facing in enumerate(facings):
        if not _needs_label(facing, ocr_threshold=ocr_threshold, confidence_threshold=confidence_threshold):
            continue
        h = max(1, int(facing["y2"]) - int(facing["y1"]))
        w = max(1, int(facing["x2"]) - int(facing["x1"]))
        queue.append(
            {
                "queue_id": f"{payload.get('scan_id', scan_path.stem)}_{idx}",
                "scan_id": payload.get("scan_id"),
                "category": payload.get("category"),
                "image_path": payload.get("image_path"),
                "box": [
                    int(facing["x1"]),
                    int(facing["y1"]),
                    int(facing["x2"]),
                    int(facing["y2"]),
                ],
                "box_normalized_hint": [
                    round(int(facing["x1"]) / max(w * 10, 1), 4),
                    round(int(facing["y1"]) / max(h * 10, 1), 4),
                    round(int(facing["x2"]) / max(w * 10, 1), 4),
                    round(int(facing["y2"]) / max(h * 10, 1), 4),
                ],
                "predicted_brand": facing.get("brand"),
                "predicted_product": facing.get("product_name"),
                "predicted_sku": facing.get("sku"),
                "pack_text": facing.get("pack_text"),
                "ocr_confidence": facing.get("ocr_confidence"),
                "confidence": facing.get("confidence"),
                "recognition_source": facing.get("recognition_source"),
                "brand": "",
                "product_name": "",
                "ocr_label": "",
                "status": "pending",
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_scan": str(scan_path),
        "category": payload.get("category"),
        "total_facings": len(facings),
        "queue_count": len(queue),
        "items": queue,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export labeling queue from scan facing dump.")
    parser.add_argument("scan_json", type=Path, help="Output from dump_scan_facings.py")
    parser.add_argument("--ocr-threshold", type=float, default=0.55)
    parser.add_argument("--confidence-threshold", type=float, default=0.65)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = export_queue(
        args.scan_json,
        ocr_threshold=args.ocr_threshold,
        confidence_threshold=args.confidence_threshold,
    )
    out_path = args.out
    if out_path is None:
        out_dir = ROOT / "data" / "labeling_queue"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"queue_{args.scan_json.stem}.json"

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), **{k: report[k] for k in ("queue_count", "total_facings")}}, indent=2))


if __name__ == "__main__":
    main()
