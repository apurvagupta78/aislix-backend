"""Read brand and product names from packaging text on YOLO crops."""

from __future__ import annotations

import os
import re
from typing import Any

import numpy as np
from PIL import Image

from app.brand_dictionary import match_from_text

_reader: Any | None = None
_reader_failed = False

OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.6"))
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes"}
OCR_UPSCALE_MIN = int(os.getenv("OCR_UPSCALE_MIN", "160"))


def _get_reader():
    global _reader, _reader_failed
    if _reader_failed:
        return None
    if _reader is not None:
        return _reader
    try:
        import easyocr

        langs = os.getenv("OCR_LANGUAGES", "en").split(",")
        _reader = easyocr.Reader([lang.strip() for lang in langs if lang.strip()], gpu=False, verbose=False)
        print(f"EasyOCR ready (languages={langs})")
        return _reader
    except Exception as exc:
        print(f"EasyOCR unavailable, OCR step skipped: {exc}")
        _reader_failed = True
        return None


def _prepare_for_ocr(image: Image.Image) -> Image.Image:
    """Upscale small YOLO crops so pack text is readable."""
    width, height = image.size
    longest = max(width, height)
    if longest >= OCR_UPSCALE_MIN:
        return image
    scale = OCR_UPSCALE_MIN / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def read_text_from_pil(image: Image.Image) -> str:
    reader = _get_reader()
    if reader is None:
        return ""
    prepared = _prepare_for_ocr(image)
    arr = np.asarray(prepared.convert("RGB"))
    try:
        lines = reader.readtext(arr, detail=0, paragraph=True)
        if isinstance(lines, list):
            return " ".join(str(line) for line in lines if line)
        return str(lines or "")
    except Exception as exc:
        print(f"OCR read failed: {exc}")
        return ""


def _clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_with_ocr(image: Image.Image, raw_text: str | None = None) -> dict | None:
    """Try to identify product from packaging text. Returns None if OCR fails or is unclear."""
    if not OCR_ENABLED:
        return None
    raw = _clean_ocr_text(raw_text if raw_text is not None else read_text_from_pil(image))
    if len(raw) < 3:
        return None

    product = match_from_text(raw)
    if not product:
        return None

    confidence = float(product.get("confidence") or 0)
    if confidence < OCR_MIN_CONFIDENCE:
        return None

    product["visible_text"] = raw[:240]
    product["confidence"] = confidence
    product["recognition_source"] = "ocr"
    return product


def read_packaging_text(image: Image.Image) -> str:
    """Always read visible text, even when brand matching fails."""
    if not OCR_ENABLED:
        return ""
    return _clean_ocr_text(read_text_from_pil(image))
