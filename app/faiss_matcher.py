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
) -> tuple[dict | None, float]:
    from app.learned_catalog import search_learned

    return search_learned(embedding, threshold=threshold)


def match_embedding(
    embedding: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[dict | None, float]:
    index, catalog = _load()
    vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
    import faiss

    faiss.normalize_L2(vec)
    scores, ids = index.search(vec, 1)
    if ids[0][0] >= 0:
        score = float(scores[0][0])
        if score >= threshold:
            entry = dict(catalog[int(ids[0][0])])
            entry["confidence"] = round(min(0.99, score), 4)
            entry["recognition_source"] = "faiss"
            return entry, score

    learned_match, learned_score = _match_with_learned(
        np.asarray(embedding, dtype=np.float32).reshape(-1),
        threshold=threshold,
    )
    if learned_match:
        return learned_match, learned_score

    if ids[0][0] < 0:
        return None, 0.0
    return None, float(scores[0][0])


def match_embeddings_batch(
    embeddings: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[tuple[dict | None, float]]:
    if len(embeddings) == 0:
        return []
    index, catalog = _load()
    vecs = np.asarray(embeddings, dtype=np.float32)
    import faiss

    faiss.normalize_L2(vecs)
    scores, ids = index.search(vecs, 1)
    results: list[tuple[dict | None, float]] = []
    for row in range(len(vecs)):
        idx = int(ids[row][0])
        score = float(scores[row][0]) if idx >= 0 else 0.0
        if idx >= 0 and score >= threshold:
            entry = dict(catalog[idx])
            entry["confidence"] = round(min(0.99, score), 4)
            entry["recognition_source"] = "faiss"
            results.append((entry, score))
            continue

        learned_match, learned_score = _match_with_learned(vecs[row], threshold=threshold)
        if learned_match:
            results.append((learned_match, learned_score))
        elif idx < 0:
            results.append((None, 0.0))
        else:
            results.append((None, score))
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
