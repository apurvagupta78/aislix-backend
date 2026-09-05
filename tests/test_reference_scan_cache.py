"""Tests for reference shelf scan cache (demo/dashboard parity)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.detector import load_image_bytes
from app.landing_leads import SAMPLE_IMAGES
from app.reference_scan_cache import (
    enrich_reference_sample_metadata,
    image_fingerprint,
    load_reference_cache,
    lookup_reference_parsed,
    sample_id_for_image,
)
from app.scan_post_process import finalize_make_scan


@pytest.fixture
def toothpaste_image() -> np.ndarray:
    path = SAMPLE_IMAGES["toothpaste-a1l"]
    return load_image_bytes(path.read_bytes())


def test_reference_cache_file_matches_fingerprint(toothpaste_image):
    entry = load_reference_cache("toothpaste-a1l")
    assert entry is not None
    assert entry["image_fingerprint"] == image_fingerprint(toothpaste_image)


def test_sample_id_for_reference_image(toothpaste_image):
    assert sample_id_for_image(toothpaste_image) == "toothpaste-a1l"


def test_lookup_reference_parsed_returns_inventory(toothpaste_image):
    parsed = lookup_reference_parsed(
        toothpaste_image,
        {"category": "Personal Care", "sub_category": "toothpaste", "sample_id": "toothpaste-a1l"},
    )
    assert parsed is not None
    assert parsed["reference_cache"] == "toothpaste-a1l"
    assert len(parsed["inventory"]) == 17


def test_visual_match_works_for_rescaled_upload(toothpaste_image):
    import cv2

    upscaled = cv2.resize(toothpaste_image, (1152, 2048), interpolation=cv2.INTER_CUBIC)
    assert sample_id_for_image(upscaled) == "toothpaste-a1l"
    parsed = lookup_reference_parsed(
        upscaled,
        {"category": "Personal Care", "sub_category": "toothpaste"},
    )
    assert parsed is not None
    assert parsed["reference_cache"] == "toothpaste-a1l"


def test_explicit_sample_id_uses_cache_without_exact_fingerprint(toothpaste_image, monkeypatch):
    monkeypatch.setenv("REFERENCE_SCAN_CACHE_STRICT_FINGERPRINT", "false")
    import cv2

    upscaled = cv2.resize(toothpaste_image, (1152, 2048), interpolation=cv2.INTER_CUBIC)
    parsed = lookup_reference_parsed(
        upscaled,
        {"sample_id": "toothpaste-a1l"},
    )
    assert parsed is not None
    assert len(parsed["inventory"]) == 17


def test_enrich_reference_sample_metadata_adds_brand_guide(toothpaste_image):
    meta = enrich_reference_sample_metadata(toothpaste_image, {"category": "Personal Care"})
    assert meta["sample_id"] == "toothpaste-a1l"
    assert meta["sub_category"] == "toothpaste"
    assert "Doctor" in meta["shelf_brand_guide"]


def test_finalize_cached_toothpaste_scan_metrics(toothpaste_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    parsed = lookup_reference_parsed(
        toothpaste_image,
        enrich_reference_sample_metadata(toothpaste_image, {}),
    )
    result = finalize_make_scan(
        toothpaste_image,
        scan_id="cache-test",
        metadata={"category": "Personal Care", "sub_category": "toothpaste"},
        parsed=parsed,
        processing_ms=50,
    )
    assert result["metrics"]["total_products"] == 112
    assert result["metrics"]["unique_skus"] == 17
    assert result["metrics"]["misplaced_products"] == 10


def test_run_make_scan_uses_reference_cache(toothpaste_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    from app.make_scan import run_make_scan_from_image

    def fail_webhook(**kwargs):
        raise AssertionError("Make webhook should not run for cached reference image")

    monkeypatch.setattr("app.make_scan.call_make_webhook", fail_webhook)
    result = run_make_scan_from_image(
        toothpaste_image,
        scan_id="cached-run",
        metadata={"category": "Personal Care", "sub_category": "toothpaste", "sample_id": "toothpaste-a1l"},
    )
    assert result["reference_cache"] == "toothpaste-a1l"
    assert result["metrics"]["total_products"] == 112
    assert result["metrics"]["unique_skus"] == 17


def test_run_make_scan_uses_cache_for_rescaled_dashboard_upload(toothpaste_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    import cv2

    from app.make_scan import run_make_scan_from_image

    def fail_webhook(**kwargs):
        raise AssertionError("Make webhook should not run for visually matched reference image")

    monkeypatch.setattr("app.make_scan.call_make_webhook", fail_webhook)
    upscaled = cv2.resize(toothpaste_image, (1152, 2048), interpolation=cv2.INTER_CUBIC)
    result = run_make_scan_from_image(
        upscaled,
        scan_id="cached-rescaled",
        metadata={"category": "Personal Care", "sub_category": "toothpaste", "location": "A-1-L"},
    )
    assert result["reference_cache"] == "toothpaste-a1l"
    assert result["metrics"]["total_products"] == 112
