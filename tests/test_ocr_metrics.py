"""Tests for OCR quality metrics."""

from __future__ import annotations

from app.metrics import ocr_quality_metrics


def test_ocr_quality_metrics_counts_empty_and_low():
    classified = [
        {"pack_text": "", "ocr_confidence": 0.0},
        {"pack_text": "Lays Magic Masala", "ocr_confidence": 0.82},
        {"pack_text": "Tomato Tango", "ocr_confidence": 0.42},
    ]
    metrics = ocr_quality_metrics(classified)
    assert metrics["ocr_empty_facings"] == 1
    assert metrics["ocr_low_confidence_facings"] == 1
    assert metrics["ocr_avg_confidence"] > 0.5
