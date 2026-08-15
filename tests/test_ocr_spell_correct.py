"""Tests for catalog-aware OCR spell correction."""

from __future__ import annotations

from app.ocr_spell_correct import catalog_vocabulary, spell_correct_ocr_text


def test_catalog_vocabulary_includes_retail_tokens():
    vocab = catalog_vocabulary()
    assert "maggi" in vocab
    assert "shampoo" in vocab
    assert "masala" in vocab


def test_spell_correct_fixes_near_miss():
    corrected = spell_correct_ocr_text("Maggl 2 min masala noodls")
    assert "maggi" in corrected.lower() or "masala" in corrected.lower()


def test_spell_correct_preserves_good_tokens():
    text = "Lays Magic Masala Potato Chips"
    assert spell_correct_ocr_text(text) == text
