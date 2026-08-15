#!/usr/bin/env python3
"""Run a scan and export per-facing debug JSON for labeling / benchmark expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import run_scan_from_bytes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump per-facing scan output for labeling.")
    parser.add_argument("image", type=Path, help="Shelf photo path")
    parser.add_argument("--category", default="", help="Aislix category string")
    parser.add_argument("--sub-category", default="", help="Sub-category slug")
    parser.add_argument("--location", default="", help="Store location code")
    parser.add_argument("--scan-id", default="", help="Optional scan id")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: data/labeling_queue/<image-stem>.json)",
    )
    args = parser.parse_args()

    metadata = {
        "category": args.category,
        "sub_category": args.sub_category,
        "location": args.location,
        "export_facings": True,
    }
    result = run_scan_from_bytes(
        args.image.read_bytes(),
        scan_id=args.scan_id or f"label-{args.image.stem}",
        metadata=metadata,
    )

    payload = {
        "scan_id": result.get("scan_id"),
        "category": result.get("category"),
        "scan_context": result.get("scan_context"),
        "metrics": result.get("metrics"),
        "image_path": str(args.image.resolve()),
        "facings": result.get("facings_debug") or [],
    }

    out_path = args.out
    if out_path is None:
        out_dir = ROOT / "data" / "labeling_queue"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.image.stem}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "facings": len(payload["facings"])}, indent=2))


if __name__ == "__main__":
    main()
