"""FAISS-backed product recognition against the built catalog."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.catalog import CATALOG_PATH, load_catalog
from app.clip_embeddings import embed_pil_images

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = BASE_DIR / "data" / "faiss.index"
DEFAULT_THRESHOLD = float(os.getenv("FAISS_SIMILARITY_THRESHOLD", "0.92"))
FAISS_SEARCH_K = int(os.getenv("FAISS_SEARCH_K", "5"))


def _entry_from_catalog(catalog: list[dict], idx: int, score: float) -> dict:
    entry = dict(catalog[int(idx)])
    entry["confidence"] = round(min(0.99, float(score)), 4)
    entry["recognition_source"] = "faiss"
    return entry


def match_embeddings_batch_topk(
    embeddings: np.ndarray,
    k: int | None = None,
    scan_context: dict | None = None,
) -> list[list[tuple[dict, float]]]:
    """Return top-K FAISS catalog matches per embedding (scores descending)."""
    if len(embeddings) == 0:
        return []
    from app.category_scope import catalog_entry_in_scope

    index, catalog = _load()
    vecs = np.asarray(embeddings, dtype=np.float32)
    import faiss

    faiss.normalize_L2(vecs)
    k = min(k or FAISS_SEARCH_K, index.ntotal)
    scores, ids = index.search(vecs, k)
    batch: list[list[tuple[dict, float]]] = []
    for row in range(len(vecs)):
        row_candidates: list[tuple[dict, float]] = []
        for idx, score in zip(ids[row], scores[row]):
            if idx < 0:
                continue
            entry = _entry_from_catalog(catalog, int(idx), float(score))
            if scan_context and not catalog_entry_in_scope(entry, scan_context):
                continue
            row_candidates.append((entry, float(score)))
        learned_match, learned_score = _match_with_learned(
            vecs[row], threshold=0.78, scan_context=scan_context
        )
        if learned_match and learned_score > 0:
            row_candidates.append((learned_match, learned_score))
            row_candidates.sort(key=lambda item: item[1], reverse=True)
            row_candidates = row_candidates[:k]
        batch.append(row_candidates)
    return batch

_index: Any | None = None
_catalog: list[dict] | None = None


def _load() -> tuple[Any, list[dict]]:
    global _index, _catalog
    if _index is not None and _catalog is not None:
        return _index, _catalog
    if not INDEX_PATH.exists() or not CATALOG_PATH.exists():
        raise FileNotFoundError(
            "FAISS index or catalog missing. Run scripts/build_faiss_index.py first."
        )
    import faiss

    _index = faiss.read_index(str(INDEX_PATH))
    _catalog = load_catalog()
    return _index, _catalog


def is_ready() -> bool:
    return INDEX_PATH.exists() and CATALOG_PATH.exists()


def _match_with_learned(
    embedding: np.ndarray,
    threshold: float,
    scan_context: dict | None = None,
) -> tuple[dict | None, float]:
    from app.learned_catalog import search_learned

    return search_learned(embedding, threshold=threshold, scan_context=scan_context)


def match_embedding(
    embedding: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    scan_context: dict | None = None,
) -> tuple[dict | None, float]:
    index, catalog = _load()
    vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
    import faiss

    faiss.normalize_L2(vec)
    k = min(FAISS_SEARCH_K, index.ntotal)
    scores, ids = index.search(vec, k)
    best_entry: dict | None = None
    best_score = 0.0
    for idx, score in zip(ids[0], scores[0]):
        if idx < 0:
            continue
        score_f = float(score)
        if score_f >= threshold and score_f > best_score:
            entry = dict(catalog[int(idx)])
            entry["confidence"] = round(min(0.99, score_f), 4)
            entry["recognition_source"] = "faiss"
            best_entry = entry
            best_score = score_f
    if best_entry:
        return best_entry, best_score

    learned_match, learned_score = _match_with_learned(
        np.asarray(embedding, dtype=np.float32).reshape(-1),
        threshold=threshold,
        scan_context=scan_context,
    )
    if learned_match:
        return learned_match, learned_score

    if ids[0][0] < 0:
        return None, 0.0
    return None, float(scores[0][0])


def match_embeddings_batch(
    embeddings: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    scan_context: dict | None = None,
) -> list[tuple[dict | None, float]]:
    if len(embeddings) == 0:
        return []
    index, catalog = _load()
    vecs = np.asarray(embeddings, dtype=np.float32)
    import faiss

    faiss.normalize_L2(vecs)
    k = min(FAISS_SEARCH_K, index.ntotal)
    scores, ids = index.search(vecs, k)
    results: list[tuple[dict | None, float]] = []
    for row in range(len(vecs)):
        best_entry: dict | None = None
        best_score = 0.0
        for idx, score in zip(ids[row], scores[row]):
            if idx < 0:
                continue
            score_f = float(score)
            if score_f >= threshold and score_f > best_score:
                entry = dict(catalog[int(idx)])
                entry["confidence"] = round(min(0.99, score_f), 4)
                entry["recognition_source"] = "faiss"
                best_entry = entry
                best_score = score_f
        if best_entry:
            results.append((best_entry, best_score))
            continue

        learned_match, learned_score = _match_with_learned(
            vecs[row], threshold=threshold, scan_context=scan_context
        )
        if learned_match:
            results.append((learned_match, learned_score))
        elif ids[row][0] < 0:
            results.append((None, 0.0))
        else:
            results.append((None, float(scores[row][0])))
    return results


def match_pil_images(
    images: list[Image.Image],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[tuple[dict | None, float]]:
    if not images:
        return []
    embeddings = embed_pil_images(images)
    return match_embeddings_batch(embeddings, threshold=threshold)


def match_pil_image(image: Image.Image, threshold: float = DEFAULT_THRESHOLD) -> tuple[dict | None, float]:
    embedding = embed_pil_images([image])[0]
    return match_embedding(embedding, threshold=threshold)
