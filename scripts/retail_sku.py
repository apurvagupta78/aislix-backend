"""Add base-catalog retail SKUs and keep FAISS aligned with catalog.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
INDEX_PATH = DATA_DIR / "faiss.index"

FaissMode = Literal["copy", "embed", "auto"]


def _load_catalog() -> tuple[dict | list, list[dict]]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = raw["products"] if isinstance(raw, dict) else raw
    return raw, products


def _save_catalog(raw: dict | list, products: list[dict]) -> None:
    if isinstance(raw, dict):
        raw["products"] = products
    CATALOG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def next_class_id(products: list[dict]) -> int:
    return max(int(p.get("class_id") or 0) for p in products) + 1


def slugify(brand: str, product_name: str, variant: str = "") -> str:
    blob = " ".join(filter(None, [brand, product_name, variant])).lower()
    blob = re.sub(r"[^a-z0-9]+", "_", blob)
    return re.sub(r"_+", "_", blob).strip("_")


def add_catalog_skus(entries: list[dict]) -> list[str]:
    """Append catalog rows for new SKUs. Returns slugs that were added."""
    raw, products = _load_catalog()
    existing = {(p.get("sku") or "").lower() for p in products}
    added: list[str] = []
    for entry in entries:
        sku = (entry.get("sku") or "").lower()
        if not sku or sku in existing:
            continue
        if entry.get("class_id") is None:
            entry = {**entry, "class_id": next_class_id(products)}
        products.append(entry)
        existing.add(sku)
        added.append(sku)
        print(f"  + catalog: {entry.get('brand')} — {entry.get('product_name')}")
    if added:
        _save_catalog(raw, products)
    return added


def sync_faiss_orphans(
    mode: FaissMode = "auto",
    *,
    register_skus: list[dict] | None = None,
) -> int:
    """
    Append FAISS vectors for catalog tail rows missing embeddings.
    Returns number of vectors appended (0 if already aligned).
    """
    from scripts.sync_faiss_orphans import register_sku_hints, sync_orphan_embeddings

    if register_skus:
        register_sku_hints(register_skus)

    resolved_mode: Literal["copy", "embed"]
    if mode == "auto":
        resolved_mode = "embed" if _torch_available() else "copy"
    else:
        resolved_mode = mode

    try:
        return sync_orphan_embeddings(resolved_mode)
    except RuntimeError as exc:
        if resolved_mode == "embed" and mode == "auto":
            print(f"CLIP embed unavailable ({exc}); falling back to copy mode.")
            return sync_orphan_embeddings("copy")
        raise


def add_retail_skus(
    entries: list[dict],
    *,
    faiss_mode: FaissMode = "auto",
    skip_faiss: bool = False,
) -> tuple[list[str], int]:
    """Add catalog SKUs then sync FAISS. Returns (added_skus, vectors_appended)."""
    added = add_catalog_skus(entries)
    if not added:
        print("No new catalog SKUs to add.")
        vectors = 0
    elif skip_faiss:
        print("Skipped FAISS sync (--skip-faiss).")
        vectors = 0
    else:
        print(f"Syncing FAISS for {len(added)} new SKU(s)...")
        vectors = sync_faiss_orphans(faiss_mode, register_skus=entries)
    if added:
        print(f"Added {len(added)} catalog SKU(s); appended {vectors} FAISS vector(s).")
    return added, vectors


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except OSError:
        return False


def parse_entry_args(args: argparse.Namespace) -> dict:
    sku = args.sku or slugify(args.brand, args.product, args.variant or "")
    return {
        "class_id": args.class_id,
        "brand": args.brand.strip(),
        "product_name": args.product.strip(),
        "variant": (args.variant or "").strip(),
        "sku": sku,
        "category": args.category.strip(),
        "donor_hint": (args.donor_hint or "").strip().lower(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Add retail SKU(s) to catalog.json and sync FAISS index."
    )
    parser.add_argument("--brand", help="Brand name (required unless --sync-only)")
    parser.add_argument("--product", help="Product name")
    parser.add_argument("--variant", default="", help="Pack size variant")
    parser.add_argument("--sku", help="SKU slug (auto-generated if omitted)")
    parser.add_argument("--category", default="General", help="Catalog category")
    parser.add_argument("--class-id", type=int, default=None, dest="class_id")
    parser.add_argument(
        "--donor-hint",
        help="Optional FAISS copy hint substring (e.g. 'smooth shine', 'mad angles')",
    )
    parser.add_argument(
        "--faiss-mode",
        choices=("auto", "copy", "embed"),
        default="auto",
        help="auto=CLIP embed when available else copy donor vectors",
    )
    parser.add_argument("--skip-faiss", action="store_true", help="Only update catalog.json")
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only sync orphan catalog rows to FAISS (no catalog changes)",
    )
    args = parser.parse_args(argv)

    if args.sync_only:
        count = sync_faiss_orphans(args.faiss_mode)
        print(f"Appended {count} FAISS vector(s).")
        return

    if not args.brand or not args.product:
        raise SystemExit("--brand and --product are required unless --sync-only.")

    entry = parse_entry_args(args)
    add_retail_skus([entry], faiss_mode=args.faiss_mode, skip_faiss=args.skip_faiss)


if __name__ == "__main__":
    main()
