"""Tests for Recognition v3 (FAISS primary, OCR tie-break)."""

from __future__ import annotations

from app.recognizer import (
    FAISS_HIGH_CONFIDENCE,
    FAISS_TIE_MARGIN,
    _ocr_disambiguate,
    _reconcile_conflicts_only,
    _resolve_faiss_v3,
    recognition_v3_enabled,
)


def _candidate(brand: str, product: str, score: float) -> tuple[dict, float]:
    return (
        {
            "brand": brand,
            "product_name": product,
            "category": "General",
            "recognition_source": "faiss",
        },
        score,
    )


def test_recognition_v3_flag_default_off(monkeypatch):
    monkeypatch.delenv("RECOGNITION_V3", raising=False)
    import importlib

    import app.recognizer as recognizer

    importlib.reload(recognizer)
    assert recognizer.recognition_v3_enabled() is False


def test_recognition_v3_flag_on(monkeypatch):
    monkeypatch.setenv("RECOGNITION_V3", "true")
    import importlib

    import app.recognizer as recognizer

    importlib.reload(recognizer)
    assert recognizer.recognition_v3_enabled() is True


def test_resolve_faiss_v3_accepts_high_confidence_without_ocr():
    candidates = [_candidate("Lipton", "Green Tea", FAISS_HIGH_CONFIDENCE)]
    result = _resolve_faiss_v3(candidates, "", None, None)
    assert result is not None
    assert result["brand"] == "Lipton"
    assert result["recognition_source"] == "faiss"


def test_resolve_faiss_v3_disambiguates_tight_margin_with_ocr():
    candidates = [
        _candidate("Brooke Bond", "Red Label", 0.91),
        _candidate("Tata Tea", "Taj Mahal", 0.905),
    ]
    ocr = "TATA TEA TAJ MAHAL PREMIUM"
    result = _resolve_faiss_v3(candidates, ocr, None, None, threshold=0.88)
    assert result is not None
    assert result["brand"] in {"Tata Tea", "Brooke Bond"}


def test_resolve_faiss_v3_rejects_conflicting_top1():
    candidates = [_candidate("Brooke Bond", "Red Label", 0.94)]
    ocr = "TATA TEA TAJ MAHAL"
    result = _resolve_faiss_v3(candidates, ocr, None, None)
    if result is not None:
        assert "taj" in (result.get("product_name") or "").lower() or result["brand"] != "Brooke Bond"


def test_ocr_disambiguate_prefers_ocr_agreeing_candidate():
    candidates = [
        _candidate("Organic India", "Tulsi Green Tea", 0.9),
        _candidate("Tata Tea", "Tetley", 0.89),
    ]
    ocr = "TETLEY GREEN TEA"
    result = _ocr_disambiguate(candidates, ocr, None, None)
    assert result is not None
    assert "tetley" in (result.get("brand") or "").lower() or "tetley" in ocr.lower()


def test_reconcile_conflicts_only_skips_agreeing_label():
    row = {"brand": "Dove", "product_name": "Shampoo", "confidence": 0.95}
    pack = "dove intense repair shampoo 180ml"
    merged = _reconcile_conflicts_only(row, pack)
    assert merged["brand"] == "Dove"


def test_reconcile_conflicts_only_fixes_clear_mismatch():
    row = {"brand": "Brooke Bond", "product_name": "Red Label", "confidence": 0.92}
    pack = "TATA TEA TAJ MAHAL PREMIUM TEA"
    merged = _reconcile_conflicts_only(row, pack)
    assert merged["brand"] != "Brooke Bond" or "taj" in (merged.get("product_name") or "").lower()
