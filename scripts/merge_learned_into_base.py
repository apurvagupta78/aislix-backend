#!/usr/bin/env python3
"""Merge runtime-learned SKUs into the base FAISS catalog (offline rebuild)."""

from __future__ import annotations

import sys
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import load_catalog, save_catalog  # noqa: E402
from app.learned_catalog import LEARNED_CATALOG_PATH, load_learned  # noqa: E402

DATA_DIR = ROOT / "data"
BASE_INDEX = DATA_DIR / "faiss.index"


def main() -> None:
    load_learned()
    if not LEARNED_CATALOG_PATH.exists():
        raise SystemExit("No learned catalog found.")

    import json

    with open(LEARNED_CATALOG_PATH, encoding="utf-8") as f:
        learned = json.load(f).get("products", [])

    if not learned:
        raise SystemExit("Learned catalog is empty.")

    base_catalog = load_catalog()
    base_index = faiss.read_index(str(BASE_INDEX))
    base_matrix = base_index.reconstruct_n(0, base_index.ntotal)

    learned_matrix = np.vstack(
        [np.asarray(item["embedding"], dtype=np.float32) for item in learned]
    ).astype(np.float32)
    faiss.normalize_L2(learned_matrix)

    merged_catalog = list(base_catalog)
    next_class_id = max((int(item.get("class_id") or 0) for item in base_catalog), default=0) + 1
    for item in learned:
        if any(existing.get("sku") == item.get("sku") for existing in merged_catalog):
            continue
        merged_catalog.append(
            {
                "class_id": next_class_id,
                "brand": item.get("brand"),
                "product_name": item.get("product_name"),
                "variant": item.get("variant"),
                "sku": item.get("sku"),
                "category": item.get("category") or "General",
            }
        )
        next_class_id += 1

    merged_matrix = np.vstack([base_matrix, learned_matrix]).astype(np.float32)
    faiss.normalize_L2(merged_matrix)
    merged_index = faiss.IndexFlatIP(merged_matrix.shape[1])
    merged_index.add(merged_matrix)

    faiss.write_index(merged_index, str(BASE_INDEX))
    save_catalog(merged_catalog)
    print(f"Merged {len(learned)} learned SKUs into base catalog ({len(merged_catalog)} total).")


if __name__ == "__main__":
    main()
