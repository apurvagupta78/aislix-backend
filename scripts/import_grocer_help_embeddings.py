"""Import Grocer-Help embeddings.json into the runtime learned catalog (+ optional Supabase).

Usage::

    py scripts/import_grocer_help_embeddings.py
    py scripts/import_grocer_help_embeddings.py --input data/grocer_help/embeddings.json --upload
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "data" / "grocer_help" / "embeddings.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Grocer-Help SKU embeddings into learned catalog.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload learned_catalog.json + learned.index to Supabase storage",
    )
    parser.add_argument(
        "--global-table",
        action="store_true",
        help="Upsert rows into global_learned_skus (requires SUPABASE_* env)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print counts only; do not write")
    return parser.parse_args()


def _upsert_global_rows(entries: list[dict]) -> int:
    import os

    import requests

    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not key:
        print("Supabase not configured — skip global_learned_skus upsert")
        return 0

    url = f"{base}/rest/v1/global_learned_skus"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    ok = 0
    for entry in entries:
        payload = {
            "sku": entry["sku"],
            "brand": entry.get("brand") or "",
            "product_name": entry.get("product_name") or "",
            "variant": entry.get("variant") or "",
            "category": entry.get("category") or "General",
            "embedding": entry["embedding"],
            "source_scan_id": entry.get("source_scan_id") or "grocer_help_import",
            "hit_count": entry.get("hit_count") or 1,
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=30).raise_for_status()
            ok += 1
        except Exception as exc:
            print(f"global upsert failed for {entry.get('sku')}: {exc}")
    return ok


def main() -> None:
    args = parse_args()
    path = args.input.resolve()
    if not path.exists():
        raise SystemExit(f"Missing {path} — run build_grocer_help_embeddings.py first")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"No records in {path}")

    if args.dry_run:
        cats: dict[str, int] = {}
        for row in raw:
            cat = row.get("category") or "General"
            cats[cat] = cats.get(cat, 0) + 1
        print(f"Would import {len(raw)} SKUs")
        for cat, n in sorted(cats.items(), key=lambda x: -x[1])[:20]:
            print(f"  {cat}: {n}")
        return

    from app.learned_catalog import import_learned_catalog, load_learned, flush_learned, count_learned

    before = load_learned()
    added = import_learned_catalog(raw)
    flush_learned()
    after = count_learned()
    print(f"Learned catalog: {before} -> {after} (+{added} new from file, {len(raw)} in import batch)")

    if args.upload:
        from app.catalog_sync import upload_learned_files
        from app.learned_catalog import LEARNED_CATALOG_PATH, LEARNED_INDEX_PATH

        upload_learned_files(LEARNED_CATALOG_PATH, LEARNED_INDEX_PATH)
        print("Uploaded learned catalog files to Supabase storage")

    if args.global_table:
        n = _upsert_global_rows(raw)
        print(f"Upserted {n}/{len(raw)} rows into global_learned_skus")


if __name__ == "__main__":
    main()
