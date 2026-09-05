"""Stable scan results for bundled reference shelf photos (demo vs dashboard parity).

This applies ONLY to known sample images under ``data/reference/`` (e.g.
``toothpaste-a1l``, ``lays-a1l``, ``shampoo-a1z``). All other shelf uploads
still run live Make.com / GPT vision — results may vary run-to-run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "reference" / "cached_scans"
VISUAL_HASH_SIZE = 16
# Same shelf photo re-uploaded at different resolution typically differs by <40 bits.
VISUAL_HASH_MAX_DISTANCE = int(os.getenv("REFERENCE_VISUAL_HASH_MAX_DISTANCE", "80"))


def reference_cache_enabled() -> bool:
    return os.getenv("REFERENCE_SCAN_CACHE", "true").lower() in {"1", "true", "yes"}


def strict_fingerprint_check() -> bool:
    return os.getenv("REFERENCE_SCAN_CACHE_STRICT_FINGERPRINT", "false").lower() in {
        "1",
        "true",
        "yes",
    }


def _canonical_size(sample_id: str) -> tuple[int, int] | None:
    from app.landing_leads import SAMPLE_IMAGES

    path = SAMPLE_IMAGES.get(sample_id)
    if path is None or not path.is_file():
        return None
    from app.detector import load_image_bytes

    ref = load_image_bytes(path.read_bytes())
    h, w = ref.shape[:2]
    return w, h


def normalize_sample_image(image: np.ndarray, sample_id: str) -> np.ndarray:
    size = _canonical_size(sample_id)
    if not size:
        return image
    width, height = size
    if image.shape[1] == width and image.shape[0] == height:
        return image
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def image_fingerprint(image: np.ndarray) -> str:
    from app.report_generator import encode_shelf_image_bytes

    return hashlib.sha256(encode_shelf_image_bytes(image)).hexdigest()


def _difference_hash(image: np.ndarray, *, size: int = VISUAL_HASH_SIZE) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    return (resized[:, 1:] > resized[:, :-1]).flatten()


def visual_hash_distance(a: np.ndarray, b: np.ndarray) -> int:
    if a.shape != b.shape:
        return 9999
    return int(np.count_nonzero(a != b))


@lru_cache(maxsize=16)
def _visual_hash_for_path(path_str: str, sample_id: str) -> np.ndarray:
    from app.detector import load_image_bytes

    path = Path(path_str)
    image = normalize_sample_image(load_image_bytes(path.read_bytes()), sample_id)
    return _difference_hash(image)


@lru_cache(maxsize=16)
def _fingerprint_for_path(path_str: str) -> str:
    from app.detector import load_image_bytes

    path = Path(path_str)
    if not path.is_file():
        return ""
    return image_fingerprint(load_image_bytes(path.read_bytes()))


def sample_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    lowered = url.lower()
    if "toothpaste-a1l" in lowered or "toothpaste_a1l" in lowered:
        return "toothpaste-a1l"
    if "lays-a1l" in lowered or "lays_rack_a1l" in lowered:
        return "lays-a1l"
    if "shampoo-a1z" in lowered or "shampoo_a1z" in lowered:
        return "shampoo-a1z"
    match = re.search(r"/landing/samples/([a-z0-9-]+)/", lowered)
    if match:
        return match.group(1)
    return None


def visual_match_sample_id(image: np.ndarray) -> str | None:
    from app.landing_leads import SAMPLE_IMAGES

    best_id: str | None = None
    best_distance = VISUAL_HASH_MAX_DISTANCE + 1
    query = _difference_hash(image)

    for sample_id, path in SAMPLE_IMAGES.items():
        if not path.is_file():
            continue
        ref_hash = _visual_hash_for_path(str(path.resolve()), sample_id)
        distance = visual_hash_distance(query, ref_hash)
        if distance < best_distance:
            best_distance = distance
            best_id = sample_id

    if best_id is not None and best_distance <= VISUAL_HASH_MAX_DISTANCE:
        return best_id
    return None


def sample_id_for_image(image: np.ndarray) -> str | None:
    from app.landing_leads import SAMPLE_IMAGES

    visual = visual_match_sample_id(image)
    if visual:
        return visual

    fp = image_fingerprint(image)
    for sample_id, path in SAMPLE_IMAGES.items():
        if path.is_file() and _fingerprint_for_path(str(path.resolve())) == fp:
            return sample_id
    return None


def resolve_reference_sample_id(
    image: np.ndarray,
    metadata: dict[str, Any] | None,
    *,
    image_url: str | None = None,
) -> str | None:
    meta = metadata or {}
    for key in ("sample_id", "reference_sample_id"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    url_sample = sample_id_from_url(image_url or meta.get("image_url"))
    if url_sample:
        return url_sample
    return sample_id_for_image(image)


def enrich_reference_sample_metadata(
    image: np.ndarray,
    metadata: dict[str, Any] | None,
    *,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Apply reference-sample defaults (brand guide, sub-category) for known shelf photos."""
    from app.landing_leads import SAMPLE_DEFAULTS

    meta = dict(metadata or {})
    sample_id = resolve_reference_sample_id(image, meta, image_url=image_url)
    if not sample_id:
        return meta

    defaults = SAMPLE_DEFAULTS.get(sample_id) or {}
    if not defaults:
        return meta

    meta["sample_id"] = sample_id
    for key in (
        "category",
        "sub_category",
        "sub_category_label",
        "location",
        "shelf_label",
        "shelf_brand_guide",
        "label",
    ):
        if defaults.get(key) and not meta.get(key):
            meta[key] = defaults[key]
    return meta


def _cache_paths(sample_id: str) -> list[Path]:
    paths = sorted(CACHE_DIR.glob(f"{sample_id}.v*.json"))
    if not paths:
        legacy = CACHE_DIR / f"{sample_id}.json"
        if legacy.is_file():
            return [legacy]

    def _version_key(path: Path) -> tuple[int, str]:
        match = re.search(r"\.v(\d+)\.json$", path.name)
        return (int(match.group(1)) if match else 0, path.name)

    return sorted(paths, key=_version_key, reverse=True)


def load_reference_cache(sample_id: str) -> dict[str, Any] | None:
    for path in _cache_paths(sample_id):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict):
            return entry
    return None


def _fingerprint_matches(sample_id: str, image: np.ndarray, entry: dict[str, Any]) -> bool:
    expected_fp = entry.get("image_fingerprint") or ""
    if not expected_fp:
        return True
    if image_fingerprint(image) == expected_fp:
        return True
    normalized = normalize_sample_image(image, sample_id)
    return image_fingerprint(normalized) == expected_fp


def lookup_reference_parsed(
    image: np.ndarray,
    metadata: dict[str, Any] | None,
    *,
    image_url: str | None = None,
) -> dict[str, Any] | None:
    """
    Return a parse_make_response-shaped payload when this image matches a cached reference shelf.
    """
    if not reference_cache_enabled():
        return None

    meta = metadata or {}
    explicit_sample = meta.get("sample_id") or meta.get("reference_sample_id") or sample_id_from_url(
        image_url or meta.get("image_url")
    )
    sample_id = resolve_reference_sample_id(image, meta, image_url=image_url)
    if not sample_id:
        return None

    entry = load_reference_cache(sample_id)
    if not entry:
        return None

    if strict_fingerprint_check() or not explicit_sample:
        if not _fingerprint_matches(sample_id, image, entry):
            if not visual_match_sample_id(image) == sample_id:
                return None

    inventory = entry.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        return None

    summary = entry.get("executive_summary") or ""
    return {
        "is_full": False,
        "raw": {"inventory": inventory, "executive_summary": summary, "reference_cache": sample_id},
        "inventory": inventory,
        "facings": None,
        "product_rows": entry.get("product_rows") or [],
        "executive_summary": summary,
        "reference_cache": sample_id,
    }
