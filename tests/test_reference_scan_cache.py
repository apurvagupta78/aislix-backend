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


def test_load_reference_cache_prefers_v2():
    entry = load_reference_cache("toothpaste-a1l")
    assert entry is not None
    assert entry.get("cache_version") == 2
    brands = {row["brand"] for row in entry["inventory"]}
    assert "Closeup" in brands
    assert not any(
        row.get("brand") == "Odol" and row.get("variant") == "Herbal"
        for row in entry["inventory"]
    )


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


def test_enrich_dashboard_tea_upload_gets_tea_brand_guide():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    meta = enrich_reference_sample_metadata(
        image,
        {
            "category": "Beverages",
            "sub_category": "tea",
            "sub_category_label": "Tea",
            "location": "A-1-L",
        },
    )
    assert "Taaza" in meta["shelf_brand_guide"]
    assert "Agni" in meta["shelf_brand_guide"]
    assert "sample_id" not in meta


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
    assert result["metrics"]["total_products"] == 116
    assert result["metrics"]["unique_skus"] == 17
    assert result["metrics"]["misplaced_products"] == 12


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
    assert result["metrics"]["total_products"] == 116
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
    assert result["metrics"]["total_products"] == 116


@pytest.fixture
def lays_image() -> np.ndarray:
    path = SAMPLE_IMAGES["lays-a1l"]
    return load_image_bytes(path.read_bytes())


def test_load_reference_cache_lays():
    entry = load_reference_cache("lays-a1l")
    assert entry is not None
    variants = {row["variant"] for row in entry["inventory"]}
    assert "India's Magic Masala" in variants
    assert "Tomato Tango" in variants
    assert sum(row["quantity"] for row in entry["inventory"]) == 36


def test_lookup_lays_cache_on_user_upload(lays_image):
    parsed = lookup_reference_parsed(
        lays_image,
        {
            "user_upload": True,
            "reference_sample_id": "lays-a1l",
            "category": "Packaged Food & Snacks",
            "sub_category": "chips",
        },
    )
    assert parsed is not None
    assert parsed["reference_cache"] == "lays-a1l"
    by_variant = {row["variant"]: row["quantity"] for row in parsed["inventory"]}
    assert by_variant["India's Magic Masala"] == 18
    assert by_variant["Tomato Tango"] == 6
    assert by_variant["American Style Cream & Onion"] == 12


def test_run_make_scan_uses_lays_cache_for_user_upload(lays_image, monkeypatch):
    monkeypatch.setenv("MAKE_LOCAL_ANNOTATE", "false")
    from app.make_scan import run_make_scan_from_image

    def fail_webhook(**kwargs):
        raise AssertionError("Make webhook should not run for cached Lay's reference image")

    monkeypatch.setattr("app.make_scan.call_make_webhook", fail_webhook)
    result = run_make_scan_from_image(
        lays_image,
        scan_id="lays-user-upload",
        metadata={
            "user_upload": True,
            "reference_sample_id": "lays-a1l",
            "category": "Packaged Food & Snacks",
            "sub_category": "chips",
            "sub_category_label": "Chips",
            "shelf_brand_guide": "BLUE = Magic Masala",
        },
    )
    assert result["reference_cache"] == "lays-a1l"
    variants = {row["variant"]: row["quantity"] for row in result["inventory"]}
    assert variants["India's Magic Masala"] == 18
    assert variants["Tomato Tango"] == 6
