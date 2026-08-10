"""Read brand and product names from packaging text on YOLO crops."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageEnhance

from app.brand_dictionary import match_from_text

EngineName = Literal["paddle", "easyocr"]
ActiveEngine = EngineName | None

_paddle_ocr: Any | None = None
_easyocr_reader: Any | None = None
_active_engine: ActiveEngine = None
_init_attempted = False

OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.6"))
OCR_LINE_MIN_CONFIDENCE = float(os.getenv("OCR_LINE_MIN_CONFIDENCE", "0.45"))
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes"}
OCR_UPSCALE_MIN = int(os.getenv("OCR_UPSCALE_MIN", "320"))
OCR_ENGINE = os.getenv("OCR_ENGINE", "easyocr").strip().lower()

SIZE_TOKEN_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(gms?|gm|g|kg|ml|ltr|l|unit|units|bags?|bag|pack|packs|pcs|pc)\b",
    re.IGNORECASE,
)


def _prepare_for_ocr(image: Image.Image) -> Image.Image:
    """Upscale small YOLO crops and boost contrast so pack text is readable."""
    width, height = image.size
    longest = max(width, height)
    if longest < OCR_UPSCALE_MIN:
        scale = OCR_UPSCALE_MIN / float(longest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(image.convert("RGB")).enhance(1.35)


def _extract_size_tokens(text: str) -> list[str]:
    return [match.group(0).strip() for match in SIZE_TOKEN_PATTERN.finditer(text)]


def _enrich_text_for_matching(text: str) -> str:
    """Append normalized size/volume tokens to help catalog variant matching."""
    sizes = _extract_size_tokens(text)
    if not sizes:
        return text
    extra = " ".join(dict.fromkeys(sizes))
    if extra.lower() in text.lower():
        return text
    return f"{text} {extra}"


def _init_paddle() -> Any | None:
    global _paddle_ocr
    if _paddle_ocr is not None:
        return _paddle_ocr
    try:
        os.environ.setdefault("FLAGS_use_mkldnn", "1")
        from paddleocr import PaddleOCR

        lang = (os.getenv("OCR_LANGUAGES", "en").split(",")[0] or "en").strip()
        _paddle_ocr = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=False,
            show_log=False,
            det_db_thresh=0.25,
            rec_batch_num=8,
        )
        print(f"PaddleOCR ready (lang={lang})")
        return _paddle_ocr
    except Exception as exc:
        print(f"PaddleOCR unavailable: {exc}")
        return None


def _init_easyocr() -> Any | None:
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    try:
        import easyocr

        langs = os.getenv("OCR_LANGUAGES", "en").split(",")
        _easyocr_reader = easyocr.Reader(
            [lang.strip() for lang in langs if lang.strip()],
            gpu=False,
            verbose=False,
        )
        print(f"EasyOCR ready (languages={langs})")
        return _easyocr_reader
    except Exception as exc:
        print(f"EasyOCR unavailable: {exc}")
        return None


def _resolve_engine() -> ActiveEngine:
    global _active_engine, _init_attempted
    if _init_attempted:
        return _active_engine
    _init_attempted = True

    preference = OCR_ENGINE
    order: list[EngineName]
    if preference == "paddle":
        order = ["paddle", "easyocr"]
    else:
        order = ["easyocr"]

    for engine in order:
        reader = _init_paddle() if engine == "paddle" else _init_easyocr()
        if reader is not None:
            _active_engine = engine
            return _active_engine

    _active_engine = None
    print("No OCR engine available — OCR step disabled.")
    return None


def _read_with_paddle(arr: np.ndarray) -> str:
    ocr = _init_paddle()
    if ocr is None:
        return ""
    try:
        result = ocr.ocr(arr, cls=True)
    except Exception as exc:
        print(f"PaddleOCR read failed: {exc}")
        return ""

    lines: list[str] = []
    for page in result or []:
        if not page:
            continue
        for item in page:
            if not item or len(item) < 2:
                continue
            text_conf = item[1]
            if not isinstance(text_conf, (list, tuple)) or len(text_conf) < 2:
                continue
            text, conf = str(text_conf[0]), float(text_conf[1])
            if text.strip() and conf >= OCR_LINE_MIN_CONFIDENCE:
                lines.append(text.strip())
    return " ".join(lines)


def _read_with_easyocr(arr: np.ndarray) -> str:
    reader = _init_easyocr()
    if reader is None:
        return ""
    try:
        lines = reader.readtext(arr, detail=0, paragraph=True)
        if isinstance(lines, list):
            return " ".join(str(line) for line in lines if line)
        return str(lines or "")
    except Exception as exc:
        print(f"EasyOCR read failed: {exc}")
        return ""


def read_text_from_pil(image: Image.Image) -> str:
    engine = _resolve_engine()
    if engine is None:
        return ""
    prepared = _prepare_for_ocr(image)
    arr = np.asarray(prepared.convert("RGB"))
    if engine == "paddle":
        return _read_with_paddle(arr)
    return _read_with_easyocr(arr)


def active_ocr_engine() -> str | None:
    """Return the OCR engine in use ('paddle' or 'easyocr'), if any."""
    return _resolve_engine()


def _clean_ocr_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def classify_with_ocr(image: Image.Image, raw_text: str | None = None) -> dict | None:
    """Try to identify product from packaging text. Returns None if OCR fails or is unclear."""
    if not OCR_ENABLED:
        return None
    raw = _clean_ocr_text(raw_text if raw_text is not None else read_text_from_pil(image))
    if len(raw) < 3:
        return None

    enriched = _enrich_text_for_matching(raw)
    product = match_from_text(enriched)
    if not product:
        return None

    confidence = float(product.get("confidence") or 0)
    if confidence < OCR_MIN_CONFIDENCE:
        return None

    sizes = _extract_size_tokens(raw)
    if sizes and not (product.get("variant") or "").strip():
        product["variant"] = sizes[0]

    product["visible_text"] = raw[:240]
    product["confidence"] = confidence
    engine = active_ocr_engine() or "ocr"
    product["recognition_source"] = f"ocr:{engine}"
    return product


def read_packaging_text(image: Image.Image) -> str:
    """Always read visible text, even when brand matching fails."""
    if not OCR_ENABLED:
        return ""
    width, height = image.size
    # Exclude bottom 15% — yellow price tags read as wrong brands (Taj Mahal, etc.).
    pack_bottom = max(1, int(height * 0.85))
    pack_crop = image.crop((0, 0, width, pack_bottom))
    full_text = _clean_ocr_text(read_text_from_pil(pack_crop))
    if pack_bottom >= 40:
        band_h = max(1, int(pack_bottom * 0.45))
        band = pack_crop.crop((0, 0, width, band_h))
        band_text = _clean_ocr_text(read_text_from_pil(band))
        if band_text and band_text.lower() not in full_text.lower():
            merged = f"{band_text} {full_text}".strip()
            return _clean_ocr_text(merged)
        if band_text and len(band_text) > len(full_text):
            return band_text
    return full_text
