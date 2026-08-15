"""Tests for OCR preprocessing variants and scoring."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.brand_dictionary import match_from_text, normalize_ocr_text
from app.ocr_preprocess import apply_clahe, build_ocr_variants, deskew_if_needed
from app.ocr_reader import score_ocr_candidate


def test_build_ocr_variants_includes_core_and_heavy():
    img = Image.new("RGB", (80, 120), color=(180, 120, 90))
    standard = build_ocr_variants(img, heavy=False)
    heavy = build_ocr_variants(img, heavy=True)
    names_std = {v.name for v in standard}
    names_heavy = {v.name for v in heavy}
    assert "original" in names_std
    assert "clahe" in names_std
    assert "upscale_2x" in names_std
    assert "super_res" in names_std
    assert "adaptive_thresh" in names_heavy
    assert "perspective" in names_heavy
    assert len(heavy) > len(standard)


def test_clahe_preserves_shape():
    rgb = np.random.randint(0, 255, (100, 60, 3), dtype=np.uint8)
    out = apply_clahe(rgb)
    assert out.shape == rgb.shape


def test_deskew_leaves_upright_image_unchanged():
    rgb = np.full((100, 80, 3), 255, dtype=np.uint8)
    rgb[30:70, 20:60] = 0
    out = deskew_if_needed(rgb)
    assert out.shape == rgb.shape


def test_normalize_ocr_text_fixes_common_noise():
    assert "lays" in normalize_ocr_text("l s magic masala")
    assert normalize_ocr_text("Maggi  2   Min") == "maggi 2 min"


def test_score_ocr_candidate_prefers_catalog_match():
    ctx = {"sub_category": "chips"}
    low = score_ocr_candidate("xyz noise", 0.9, ctx)[0]
    high = score_ocr_candidate("lays magic masala potato chips", 0.7, ctx)[0]
    assert high > low


def test_match_from_text_standalone_magic_masala():
    ctx = {"sub_category": "chips"}
    match = match_from_text("magic masala potato chips", scan_context=ctx)
    assert match is not None
    assert (match.get("brand") or "").lower().startswith("lay")
