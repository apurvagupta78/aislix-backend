#!/usr/bin/env python3
"""Merge human-labeled corrections into the benchmark manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_items(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "items" in payload:
            return payload["items"]
        if "facings" in payload:
            return payload["facings"]
        if "cases" in payload:
            rows: list[dict] = []
            for case in payload["cases"]:
                rows.extend(case.get("facings") or [])
            return rows
    return []


def import_corrections(
    manifest_path: Path,
    corrections_path: Path,
    *,
    case_id: str | None,
    create_case: bool,
) -> dict:
    manifest = _load_json(manifest_path)
    corrections = _normalize_items(_load_json(corrections_path))

    cases = manifest.setdefault("cases", [])
    target_case = None
    if case_id:
        for case in cases:
            if case.get("id") == case_id:
                target_case = case
                break
    if target_case is None and corrections:
        inferred_id = corrections[0].get("case_id") or case_id
        if inferred_id:
            for case in cases:
                if case.get("id") == inferred_id:
                    target_case = case
                    break

    if target_case is None and create_case and corrections:
        inferred_id = case_id or corrections[0].get("case_id") or "imported_case"
        target_case = {
            "id": inferred_id,
            "location": corrections[0].get("location") or "",
            "category": corrections[0].get("category") or "General",
            "sub_category": corrections[0].get("sub_category"),
            "image": corrections[0].get("image") or f"images/{inferred_id}.jpg",
            "facings": [],
        }
        cases.append(target_case)

    if target_case is None:
        raise ValueError("Target benchmark case not found; pass --case-id or --create-case")

    existing = target_case.setdefault("facings", [])
    existing_ids = {f.get("id") for f in existing if f.get("id")}
    added = 0
    updated = 0

    for item in corrections:
        brand = (item.get("brand") or item.get("corrected_brand") or "").strip()
        product = (item.get("product_name") or item.get("corrected_product") or "").strip()
        ocr_label = (item.get("ocr_label") or item.get("corrected_ocr_label") or product).strip()
        box = item.get("box")
        if not box or len(box) != 4:
            continue
        if not brand and not product:
            continue

        facing = {
            "id": item.get("id") or item.get("queue_id") or f"import_{added + updated + 1}",
            "brand": brand,
            "product_name": product,
            "ocr_label": ocr_label,
            "box": box,
        }
        if item.get("sku"):
            facing["sku"] = item["sku"]

        if facing["id"] in existing_ids:
            for idx, row in enumerate(existing):
                if row.get("id") == facing["id"]:
                    existing[idx] = {**row, **facing}
                    updated += 1
                    break
        else:
            existing.append(facing)
            existing_ids.add(facing["id"])
            added += 1

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"case_id": target_case["id"], "added": added, "updated": updated, "total_facings": len(existing)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import labeled corrections into benchmark manifest.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "benchmark" / "manifest.json",
    )
    parser.add_argument("corrections", type=Path, help="Labeling queue JSON or corrections list")
    parser.add_argument("--case-id", default=None, help="Benchmark case id (e.g. tea_a1s)")
    parser.add_argument("--create-case", action="store_true", help="Create case if missing")
    args = parser.parse_args()

    stats = import_corrections(
        args.manifest,
        args.corrections,
        case_id=args.case_id,
        create_case=args.create_case,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
