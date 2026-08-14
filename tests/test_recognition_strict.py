"""Tests for strict FAISS→OCR→Unknown recognition pipeline."""

from __future__ import annotations

from app.recognizer import (
    FAISS_STRICT_LEARNED_MIN,
    FAISS_STRICT_THRESHOLD,
    _strict_faiss_accept,
    recognition_strict_enabled,
)
from app.scan_context import resolve_scan_context


def _chips_context() -> dict:
    return resolve_scan_context(
        {"category": "Packaged Food & Snacks · Chips", "location": "A-1-L"}
    )


def test_strict_gpt_fallback_respects_env(monkeypatch):
    monkeypatch.setenv("STRICT_GPT_FALLBACK", "false")
    import importlib

    import app.recognizer as recognizer

    importlib.reload(recognizer)
    assert recognizer.strict_gpt_fallback_enabled() is False
    monkeypatch.setenv("STRICT_GPT_FALLBACK", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    importlib.reload(recognizer)
    assert recognizer.strict_gpt_fallback_enabled() is False
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    importlib.reload(recognizer)
    assert recognizer.strict_gpt_fallback_enabled() is True


def test_strict_mode_enabled_by_default(monkeypatch):
    monkeypatch.delenv("RECOGNITION_STRICT", raising=False)
    monkeypatch.delenv("RECOGNITION_LEGACY_V2", raising=False)
    import importlib

    import app.recognizer as recognizer

    importlib.reload(recognizer)
    assert recognizer.recognition_strict_enabled() is True


def test_strict_rejects_weak_learned_faiss_on_chips():
    ctx = _chips_context()
    match = {
        "brand": "TooYumm",
        "product_name": "Tooyumm",
        "sku": "tooyumm_tooyumm",
        "category": "General",
        "recognition_source": "learned",
    }
    assert _strict_faiss_accept(match, 0.96, None, ctx) is False
    assert _strict_faiss_accept(match, 0.99, None, ctx, "TooYumm masala") is False


def test_strict_accepts_base_catalog_faiss_when_ocr_agrees():
    ctx = _chips_context()
    match = {
        "brand": "Lays",
        "product_name": "Classic Salted Potato Chips",
        "sku": "lays_classic_salted_potato_chips",
        "category": "General",
        "recognition_source": "faiss",
    }
    assert _strict_faiss_accept(match, FAISS_STRICT_THRESHOLD, None, ctx) is False
    assert _strict_faiss_accept(
        match, FAISS_STRICT_THRESHOLD, None, ctx, "Lay's Classic Salted Potato Chips"
    ) is True


def test_strict_rejects_haldiram_faiss_without_lays_in_ocr():
    ctx = _chips_context()
    match = {
        "brand": "Haldiram",
        "product_name": "Namkeen Navratan Mix Pouch",
        "sku": "haldiram_navratan",
        "category": "General",
        "recognition_source": "learned",
    }
    assert _strict_faiss_accept(match, 0.983, None, ctx) is False
    assert _strict_faiss_accept(match, 0.983, None, ctx, "Lay's American Style Cream Onion") is False


def test_strict_learned_requires_higher_score():
    ctx = _chips_context()
    match = {
        "brand": "Lays",
        "product_name": "Classic Salted Potato Chips",
        "sku": "lays_classic",
        "category": "General",
        "recognition_source": "learned",
    }
    assert _strict_faiss_accept(match, FAISS_STRICT_THRESHOLD, None, ctx) is False
    assert _strict_faiss_accept(match, FAISS_STRICT_LEARNED_MIN, None, ctx) is False
    assert _strict_faiss_accept(
        match, FAISS_STRICT_LEARNED_MIN, None, ctx, "Lay's Classic Salted Potato Chips"
    ) is True


def test_strict_wins_over_v3_when_both_enabled(monkeypatch):
    monkeypatch.setenv("RECOGNITION_STRICT", "true")
    monkeypatch.setenv("RECOGNITION_V3", "true")
    monkeypatch.delenv("RECOGNITION_LEGACY_V2", raising=False)
    import importlib

    import app.recognizer as recognizer

    importlib.reload(recognizer)
    assert recognizer.recognition_strict_enabled() is True
    assert recognizer.active_recognition_mode() == "strict"
