#!/usr/bin/env python3
"""Report benchmark labeling coverage vs Aislix category tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.accuracy_benchmark import category_key  # noqa: E402


def build_coverage(manifest_path: Path, categories_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    categories = json.loads(categories_path.read_text(encoding="utf-8"))

    labeled_by_sub: dict[str, int] = {}
    cases_by_sub: dict[str, int] = {}
    for case in manifest.get("cases", []):
        key = category_key(case)
        cases_by_sub[key] = cases_by_sub.get(key, 0) + 1
        labeled_by_sub[key] = labeled_by_sub.get(key, 0) + len(case.get("facings") or [])

    rows = []
    for cat in categories:
        for sub in cat.get("subcategories", []):
            sub_id = sub["id"]
            rows.append(
                {
                    "category": cat["name"],
                    "sub_category": sub_id,
                    "sub_category_label": sub["label"],
                    "target_labeled_facings": 12,
                    "benchmark_cases": cases_by_sub.get(sub_id, 0),
                    "labeled_facings": labeled_by_sub.get(sub_id, 0),
                    "status": (
                        "ready"
                        if labeled_by_sub.get(sub_id, 0) >= 12
                        else "partial"
                        if labeled_by_sub.get(sub_id, 0) > 0
                        else "missing"
                    ),
                }
            )

    return {
        "summary": {
            "total_subcategories": len(rows),
            "ready": sum(1 for r in rows if r["status"] == "ready"),
            "partial": sum(1 for r in rows if r["status"] == "partial"),
            "missing": sum(1 for r in rows if r["status"] == "missing"),
            "total_labeled_facings": sum(labeled_by_sub.values()),
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Category labeling coverage report.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "benchmark" / "manifest.json")
    parser.add_argument("--categories", type=Path, default=ROOT / "data" / "categories.json")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "benchmark" / "category_coverage.json")
    args = parser.parse_args()

    report = build_coverage(args.manifest, args.categories)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
