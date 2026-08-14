"""Tests for snack learned-SKU pollution pruning and catalog-only GPT on chips."""

from __future__ import annotations

import numpy as np

from app.learned_catalog import (
    _is_snack_visual_pollution,
    is_learnable,
    learn_sku,
    load_learned,
)
from app.recognizer import catalog_candidates_for_scan, classify_with_gpt
from app.scan_context import resolve_scan_context


def _chips_context() -> dict:
    return resolve_scan_context(
        {"category": "Packaged Food & Snacks · Chips", "location": "A-1-L"}
    )


def test_snack_visual_pollution_detects_tooyumm_and_haldiram_on_lays_flavors():
    assert _is_snack_visual_pollution(
        {"brand": "TooYumm", "product_name": "Masala", "sku": "tooyumm_masala"}
    )
    assert _is_snack_visual_pollution(
        {
            "brand": "Haldiram",
            "product_name": "Magic Masala Potato Chips",
            "sku": "haldiram_magic_masala_potato_chips",
        }
    )
    assert not _is_snack_visual_pollution(
        {
            "brand": "Lays",
            "product_name": "Magic Masala Potato Chips",
            "sku": "lays_magic_masala_potato_chips",
        }
    )


def test_is_learnable_rejects_snack_pollution():
    assert not is_learnable(
        {
            "brand": "TooYumm",
            "product_name": "Masala",
            "confidence": 0.9,
            "recognition_source": "gpt",
        }
    )


def test_learn_sku_blocks_polluted_snack_labels(monkeypatch):
    monkeypatch.setattr("app.learned_catalog._loaded", True)
    monkeypatch.setattr("app.learned_catalog._learned_catalog", [])
    monkeypatch.setattr("app.learned_catalog._learned_index", None)
    monkeypatch.setattr("app.learned_catalog._persist_unlocked", lambda *args, **kwargs: None)

    vector = np.ones(512, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    label = {
        "brand": "Haldiram",
        "product_name": "Magic Masala",
        "confidence": 0.92,
        "recognition_source": "gpt",
    }
    assert learn_sku(vector, label, scan_id="test") is False


def test_catalog_candidates_for_chips_scan():
    ctx = _chips_context()
    candidates = catalog_candidates_for_scan(ctx, limit=200)
    assert candidates
    brands = {(row.get("brand") or "").lower() for row in candidates}
    assert "lays" in brands
    assert "tooyumm" not in brands


def test_classify_with_gpt_on_snacks_uses_catalog_gpt(monkeypatch):
    ctx = _chips_context()
    calls: list[str] = []

    def fake_catalog_gpt(image, ocr_hint="", scan_context=None):
        calls.append("catalog")
        return {
            "brand": "Lays",
            "product_name": "Magic Masala Potato Chips",
            "confidence": 0.88,
            "recognition_source": "gpt_planogram",
            "category": "Snacks",
            "sku": "lays_magic_masala_potato_chips",
        }

    def fake_open_gpt(image, ocr_hint="", scan_context=None):
        calls.append("open")
        return {
            "brand": "Haldiram",
            "product_name": "Namkeen",
            "confidence": 0.9,
            "recognition_source": "gpt",
            "category": "Snacks",
            "sku": "haldiram_namkeen",
        }

    monkeypatch.setattr("app.recognizer._classify_with_catalog_gpt", fake_catalog_gpt)

    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    result = classify_with_gpt(img, ocr_hint="Lay's Magic", scan_context=ctx)
    assert calls == ["catalog"]
    assert result["brand"] == "Lays"
    assert fake_open_gpt  # silence unused warning
