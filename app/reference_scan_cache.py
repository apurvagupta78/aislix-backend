"""Stable scan results for bundled reference shelf photos (demo vs dashboard parity)."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "reference" / "cached_scans"


def reference_cache_enabled() -> bool:
    return os.getenv("REFERENCE_SCAN_CACHE", "true").lower() in {"1", "true", "yes"}


def image_fingerprint(image: np.ndarray) -> str:
    from app.report_generator import encode_shelf_image_bytes

    return hashlib.sha256(encode_shelf_image_bytes(image)).hexdigest()


@lru_cache(maxsize=16)
def _fingerprint_for_path(path_str: str) -> str:
    from app.detector import load_image_bytes

    path = Path(path_str)
    if not path.is_file():
        return ""
    return image_fingerprint(load_image_bytes(path.read_bytes()))


def sample_id_for_image(image: np.ndarray) -> str | None:
    from app.landing_leads import SAMPLE_IMAGES

    fp = image_fingerprint(image)
    for sample_id, path in SAMPLE_IMAGES.items():
        if path.is_file() and _fingerprint_for_path(str(path.resolve())) == fp:
            return sample_id
    return None


def enrich_reference_sample_metadata(
    image: np.ndarray,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply reference-sample defaults (brand guide, sub-category) for known shelf photos."""
    from app.landing_leads import SAMPLE_DEFAULTS

    meta = dict(metadata or {})
    sample_id = meta.get("sample_id") or meta.get("reference_sample_id") or sample_id_for_image(image)
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


def _cache_path(sample_id: str) -> Path:
    return CACHE_DIR / f"{sample_id}.v1.json"


def load_reference_cache(sample_id: str) -> dict[str, Any] | None:
    path = _cache_path(sample_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def lookup_reference_parsed(
    image: np.ndarray,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Return a parse_make_response-shaped payload when this image matches a cached reference shelf.
    """
    if not reference_cache_enabled():
        return None

    meta = metadata or {}
    sample_id = meta.get("sample_id") or meta.get("reference_sample_id") or sample_id_for_image(image)
    if not sample_id:
        return None

    entry = load_reference_cache(sample_id)
    if not entry:
        return None

    expected_fp = entry.get("image_fingerprint") or ""
    if expected_fp and image_fingerprint(image) != expected_fp:
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
