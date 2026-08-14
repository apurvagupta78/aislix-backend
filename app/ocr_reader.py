"""Read brand and product names from packaging text on YOLO crops."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from app.brand_dictionary import match_from_text

EngineName = Literal["paddle", "easyocr"]
ActiveEngine = EngineName | None

_paddle_ocr: Any | None = None
_easyocr_reader: Any | None = None
_active_engine: ActiveEngine = None
_init_attempted = False
_paddle_init_error: str | None = None

OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.6"))
OCR_LINE_MIN_CONFIDENCE = float(os.getenv("OCR_LINE_MIN_CONFIDENCE", "0.45"))
OCR_SHORT_WORD_MIN_CONFIDENCE = float(os.getenv("OCR_SHORT_WORD_MIN_CONFIDENCE", "0.32"))
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes"}
OCR_UPSCALE_MIN = int(os.getenv("OCR_UPSCALE_MIN", "480"))
OCR_ENGINE = os.getenv("OCR_ENGINE", "easyocr").strip().lower()

SIZE_TOKEN_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(gms?|gm|g|kg|ml|ltr|l|unit|units|bags?|bag|pack|packs|pcs|pc)\b",
    re.IGNORECASE,
)


def _upscale_if_small(image: Image.Image) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest < OCR_UPSCALE_MIN:
        scale = OCR_UPSCALE_MIN / float(longest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def _prepare_for_ocr(image: Image.Image, *, contrast: float = 1.35) -> Image.Image:
    """Upscale small YOLO crops, sharpen, and boost contrast so pack text is readable."""
    image = _upscale_if_small(image.convert("RGB"))
    image = image.filter(ImageFilter.SHARPEN)
    return ImageEnhance.Contrast(image).enhance(contrast)


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
    global _paddle_ocr, _paddle_init_error
    if _paddle_ocr is not None:
        return _paddle_ocr
    try:
        # MKLDNN can crash on some Railway CPU hosts; prefer plain CPU ops.
        os.environ["FLAGS_use_mkldnn"] = "0"
        from paddleocr import PaddleOCR

        lang = (os.getenv("OCR_LANGUAGES", "en").split(",")[0] or "en").strip()
        base_kwargs = {
            "use_angle_cls": True,
            "lang": lang,
            "use_gpu": False,
            "show_log": False,
            "det_db_thresh": 0.25,
            "rec_batch_num": 8,
        }
        try:
            _paddle_ocr = PaddleOCR(**base_kwargs, enable_mkldnn=False)
        except TypeError:
            _paddle_ocr = PaddleOCR(**base_kwargs)
        _paddle_init_error = None
        print(f"PaddleOCR ready (lang={lang}, home={os.path.expanduser('~')})")
        return _paddle_ocr
    except Exception as exc:
        _paddle_init_error = str(exc)
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


def _line_confidence_ok(text: str, conf: float) -> bool:
    token = re.sub(r"[^a-zA-Z0-9]", "", text)
    if len(token) <= 5:
        return conf >= OCR_SHORT_WORD_MIN_CONFIDENCE
    return conf >= OCR_LINE_MIN_CONFIDENCE


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
            if text.strip() and _line_confidence_ok(text, conf):
                lines.append(text.strip())
    return " ".join(lines)


def _read_with_easyocr(arr: np.ndarray) -> str:
    reader = _init_easyocr()
    if reader is None:
        return ""
    try:
        detailed = reader.readtext(arr, detail=1, paragraph=False)
        lines: list[str] = []
        for item in detailed or []:
            if not item or len(item) < 3:
                continue
            text, conf = str(item[1]), float(item[2])
            if text.strip() and _line_confidence_ok(text, conf):
                lines.append(text.strip())
        if lines:
            return " ".join(lines)
        fallback = reader.readtext(arr, detail=0, paragraph=True)
        if isinstance(fallback, list):
            return " ".join(str(line) for line in fallback if line)
        return str(fallback or "")
    except Exception as exc:
        print(f"EasyOCR read failed: {exc}")
        return ""


def _read_text_variants(image: Image.Image) -> str:
    """Run OCR at multiple contrast levels and merge unique tokens."""
    engine = _resolve_engine()
    if engine is None:
        return ""

    chunks: list[str] = []
    seen_lower: set[str] = set()
    for contrast in (1.25, 1.55):
        prepared = _prepare_for_ocr(image, contrast=contrast)
        arr = np.asarray(prepared.convert("RGB"))
        raw = _read_with_paddle(arr) if engine == "paddle" else _read_with_easyocr(arr)
        for token in raw.split():
            key = token.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                chunks.append(token)
    return " ".join(chunks)


def read_text_from_pil(image: Image.Image) -> str:
    if _resolve_engine() is None:
        return ""
    return _read_text_variants(image)


def active_ocr_engine() -> str | None:
    """Return the OCR engine in use ('paddle' or 'easyocr'), if any."""
    return _resolve_engine()


def ocr_engine_status() -> dict:
    """Configured vs active OCR engine — useful when Paddle falls back to EasyOCR."""
    _resolve_engine()
    active = _active_engine
    requested = OCR_ENGINE
    fallback = None
    if requested == "paddle" and active == "easyocr":
        fallback = _paddle_init_error or "PaddleOCR init failed; using EasyOCR fallback"
    elif requested not in {"paddle", "easyocr"}:
        fallback = f"Unknown OCR_ENGINE={requested!r}; using {active or 'none'}"
    return {
        "ocr_engine": active or "none",
        "ocr_engine_requested": requested,
        "ocr_fallback_reason": fallback,
    }


def _clean_ocr_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _merge_ocr_texts(*parts: str) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for token in _clean_ocr_text(part).split():
            key = token.lower()
            if key not in seen:
                seen.add(key)
                merged.append(token)
    return " ".join(merged)


def classify_with_ocr(
    image: Image.Image,
    raw_text: str | None = None,
    scan_context: dict | None = None,
) -> dict | None:
    """Try to identify product from packaging text. Returns None if OCR fails or is unclear."""
    if not OCR_ENABLED:
        return None
    raw = _clean_ocr_text(raw_text if raw_text is not None else read_text_from_pil(image))
    if len(raw) < 3:
        return None

    enriched = _enrich_text_for_matching(raw)
    product = match_from_text(enriched, scan_context=scan_context)
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
        top_band = pack_crop.crop((0, 0, width, band_h))
        top_text = _clean_ocr_text(read_text_from_pil(top_band))
        center_top = max(1, int(pack_bottom * 0.2))
        center_bottom = min(pack_bottom, int(pack_bottom * 0.65))
        center_band = pack_crop.crop((0, center_top, width, center_bottom))
        center_text = _clean_ocr_text(read_text_from_pil(center_band))
        return _merge_ocr_texts(top_text, center_text, full_text)
    return full_text
