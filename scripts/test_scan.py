"""Quick local scan test script."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline import run_scan_from_bytes  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/test_scan.py <image-path>")
    image_path = Path(sys.argv[1])
    data = image_path.read_bytes()
    result = run_scan_from_bytes(data, scan_id="local-test")
    summary = {
        "scan_id": result.get("scan_id"),
        "total_products": result.get("total_products"),
        "metrics": result.get("metrics"),
        "inventory_count": len(result.get("inventory", [])),
        "top_inventory": result.get("inventory", [])[:5],
        "faiss_vs_gpt": {},
    }
    sources = {}
    for p in result.get("products", []):
        src = p.get("recognition_source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    summary["recognition_sources"] = sources
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
