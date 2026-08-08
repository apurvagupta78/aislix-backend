"""Runtime-learned SKU catalog — GPT discoveries reused via FAISS on future scans."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from app.catalog import infer_category

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LEARNED_CATALOG_PATH = DATA_DIR / "learned_catalog.json"
LEARNED_INDEX_PATH = DATA_DIR / "learned.index"

_lock = threading.Lock()
_learned_index: Any | None = None
_learned_catalog: list[dict] = []
_loaded = False
_pending_updates: list[dict] = []


def metadata_to_sku(brand: str, product_name: str, variant: str = "") -> str:
    parts = [brand, product_name, variant]
    slug = "_".join(
        re.sub(r"[^a-z0-9]+", "_", part.strip().lower()).strip("_")
        for part in parts
        if part and part.strip()
    )
    slug = re.sub(r"_+", "_", slug).strip("_")
    return (slug[:120] or f"learned_{uuid.uuid4().hex[:8]}")


def is_learnable(label: dict) -> bool:
    source = label.get("recognition_source")
    if source not in {"gpt", "ocr"}:
        return False
    if float(label.get("confidence") or 0) < float(os.getenv("LEARN_MIN_CONFIDENCE", "0.7")):
        return False
    brand = (label.get("brand") or "").strip()
    product = (label.get("product_name") or "").strip()
    if not brand or not product:
        return False
    lowered_brand = brand.lower()
    lowered_product = product.lower()
    if lowered_brand in {"unknown", "n/a", "na"}:
        return False
    if lowered_product in {"unknown", "unknown product", "unidentified sku", "n/a"}:
        return False
    return True


def count_learned() -> int:
    return len(_learned_catalog)


def load_learned() -> int:
    global _learned_index, _learned_catalog, _loaded
    with _lock:
        if _loaded:
            return len(_learned_catalog)

        from app.catalog_sync import download_learned_files, fetch_learned_from_supabase

        download_learned_files(LEARNED_CATALOG_PATH, LEARNED_INDEX_PATH)
        remote = fetch_learned_from_supabase()
        if remote:
            _learned_catalog = remote
        elif LEARNED_CATALOG_PATH.exists():
            with open(LEARNED_CATALOG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _learned_catalog = data if isinstance(data, list) else data.get("products", [])

        _rebuild_index_unlocked()
        _loaded = True
        print(f"Loaded {len(_learned_catalog)} learned SKUs")
        return len(_learned_catalog)


def import_learned_catalog(entries: list[dict]) -> int:
    """Merge learned SKUs sent from Lovable (no Railway Supabase key required)."""
    global _loaded
    if not entries:
        return count_learned()
    with _lock:
        added = 0
        for raw in entries:
            sku = (raw.get("sku") or "").strip()
            embedding = raw.get("embedding")
            if not sku or not embedding:
                continue
            if any(entry.get("sku") == sku for entry in _learned_catalog):
                continue
            vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm
            _learned_catalog.append(
                {
                    "sku": sku,
                    "brand": raw.get("brand") or "",
                    "product_name": raw.get("product_name") or "",
                    "variant": raw.get("variant") or "",
                    "category": raw.get("category") or "General",
                    "embedding": vector.astype(float).tolist(),
                    "hit_count": int(raw.get("hit_count") or 1),
                    "source_scan_id": raw.get("source_scan_id"),
                    "recognition_source": "learned",
                }
            )
            added += 1
        if added:
            _rebuild_index_unlocked()
        _loaded = True
        if added:
            print(f"Imported {added} learned SKU(s) from Lovable")
        return len(_learned_catalog)


def pop_learned_updates() -> list[dict]:
    """Return newly learned SKUs from the latest scan for Lovable to persist."""
    global _pending_updates
    with _lock:
        updates = _pending_updates[:]
        _pending_updates = []
    return updates


def _rebuild_index_unlocked() -> None:
    global _learned_index
    if not _learned_catalog:
        _learned_index = None
        return
    import faiss

    matrix = np.vstack(
        [np.asarray(entry["embedding"], dtype=np.float32) for entry in _learned_catalog]
    )
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    _learned_index = index


def search_learned(
    embedding: np.ndarray,
    threshold: float = 0.85,
) -> tuple[dict | None, float]:
    if _learned_index is None or not _learned_catalog:
        return None, 0.0
    import faiss

    vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
    faiss.normalize_L2(vec)
    scores, ids = _learned_index.search(vec, 1)
    idx = int(ids[0][0])
    if idx < 0:
        return None, 0.0
    score = float(scores[0][0])
    if score < threshold:
        return None, score
    entry = dict(_learned_catalog[idx])
    entry["confidence"] = round(min(0.99, score), 4)
    entry["recognition_source"] = "learned"
    return entry, score


def learn_sku(
    embedding: np.ndarray,
    label: dict,
    scan_id: str | None = None,
) -> bool:
    if not is_learnable(label):
        return False

    brand = (label.get("brand") or "").strip()
    product = (label.get("product_name") or "").strip()
    variant = (label.get("variant") or "").strip()
    category = label.get("category") or infer_category(metadata_to_sku(brand, product, variant))
    sku = metadata_to_sku(brand, product, variant)
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm

    with _lock:
        for entry in _learned_catalog:
            if entry.get("sku") == sku:
                entry["hit_count"] = int(entry.get("hit_count") or 1) + 1
                _persist_unlocked(entry)
                return False

        new_entry = {
            "sku": sku,
            "brand": brand,
            "product_name": product,
            "variant": variant,
            "category": category,
            "embedding": vector.astype(float).tolist(),
            "hit_count": 1,
            "source_scan_id": scan_id,
            "recognition_source": "learned",
        }
        _learned_catalog.append(new_entry)

        import faiss

        vec = vector.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(vec)
        if _learned_index is None:
            _rebuild_index_unlocked()
        else:
            _learned_index.add(vec)

        _persist_unlocked(new_entry)
        _pending_updates.append(dict(new_entry))
        print(f"Learned new SKU: {sku} (scan={scan_id})")
        return True


def _persist_unlocked(changed_entry: dict | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEARNED_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump({"products": _learned_catalog}, f, indent=2)
    if _learned_index is not None:
        import faiss

        faiss.write_index(_learned_index, str(LEARNED_INDEX_PATH))

    from app.catalog_sync import upload_learned_files, upsert_learned_row

    upload_learned_files(LEARNED_CATALOG_PATH, LEARNED_INDEX_PATH)
    if changed_entry:
        upsert_learned_row(changed_entry)


def flush_learned() -> None:
    with _lock:
        if _learned_catalog:
            _persist_unlocked()
