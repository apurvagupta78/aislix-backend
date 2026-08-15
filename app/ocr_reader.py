"""Read brand and product names from packaging text on YOLO crops."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from app.brand_dictionary import match_from_text, normalize_ocr_text
from app.ocr_preprocess import OcrVariant, build_ocr_variants

EngineName = Literal["paddle", "easyocr"]
ActiveEngine = EngineName | None

_paddle_ocr: Any | None = None
_paddle_ocr_by_lang: dict[str, Any] = {}
_easyocr_reader: Any | None = None
_active_engine: ActiveEngine = None
_init_attempted = False
_paddle_init_error: str | None = None

OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.6"))
OCR_LINE_MIN_CONFIDENCE = float(os.getenv("OCR_LINE_MIN_CONFIDENCE", "0.45"))
OCR_SHORT_WORD_MIN_CONFIDENCE = float(os.getenv("OCR_SHORT_WORD_MIN_CONFIDENCE", "0.32"))
OCR_LOW_CONFIDENCE = float(os.getenv("OCR_LOW_CONFIDENCE", "0.55"))
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes"}
OCR_UPSCALE_MIN = int(os.getenv("OCR_UPSCALE_MIN", "480"))
OCR_AGGRESSIVE_TARGET = int(os.getenv("OCR_AGGRESSIVE_TARGET", "1280"))
OCR_CROP_PADDING = float(os.getenv("OCR_CROP_PADDING", "0.10"))
OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle").strip().lower()
OCR_PADDLE_REC_MODEL = os.getenv("OCR_PADDLE_REC_MODEL", "mobile").strip().lower()
OCR_DET_DB_UNCLIP_RATIO = float(os.getenv("OCR_DET_DB_UNCLIP_RATIO", "1.6"))
OCR_REC_ONLY_BANDS = os.getenv("OCR_REC_ONLY_BANDS", "true").lower() in {"1", "true", "yes"}
OCR_PADDLE_REC_MODEL_DIR = os.getenv("OCR_PADDLE_REC_MODEL_DIR", "").strip()
OCR_FULL_MODE = os.getenv("OCR_FULL_MODE", "false").lower() in {"1", "true", "yes"}
OCR_FAST_MODE = os.getenv("OCR_FAST_MODE", "true").lower() in {"1", "true", "yes"} and not OCR_FULL_MODE
OCR_MULTILANG_MERGE = (
    os.getenv("OCR_MULTILANG_MERGE", "false" if OCR_FAST_MODE else "true").lower()
    in {"1", "true", "yes"}
)

SIZE_TOKEN_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(gms?|gm|g|kg|ml|ltr|l|unit|units|bags?|bag|pack|packs|pcs|pc)\b",
    re.IGNORECASE,
)


@dataclass
class OcrReadResult:
    text: str
    confidence: float
    variant: str
    catalog_score: float
    score: float
    attempts: int = 1


def flavor_focus_crop(image: Image.Image) -> Image.Image:
    """Middle band where Lay's flavor names sit (below logo, above weight)."""
    width, height = image.size
    if width < 12 or height < 12:
        return image
    left = int(width * 0.06)
    right = int(width * 0.94)
    top = int(height * 0.35)
    bottom = int(height * 0.72)
    if right - left < 8 or bottom - top < 8:
        return image
    return image.crop((left, top, right, bottom))


def logo_focus_crop(image: Image.Image) -> Image.Image:
    """Center band where brand logos sit on upright snack bags."""
    width, height = image.size
    if width < 12 or height < 12:
        return image
    left = int(width * 0.08)
    right = int(width * 0.92)
    top = int(height * 0.12)
    bottom = int(height * 0.55)
    if right - left < 8 or bottom - top < 8:
        return image
    return image.crop((left, top, right, bottom))


def center_logo_crop(image: Image.Image) -> Image.Image:
    """Brand-agnostic logo band for mixed snack/carton packs."""
    width, height = image.size
    if width < 12 or height < 12:
        return image
    left = int(width * 0.10)
    right = int(width * 0.90)
    top = int(height * 0.15)
    bottom = int(height * 0.50)
    if right - left < 8 or bottom - top < 8:
        return image
    return image.crop((left, top, right, bottom))


def shelf_edge_crop(image: Image.Image) -> Image.Image:
    """Bottom band where store shelf edge labels (SEL) often show brand + variant clearly."""
    width, height = image.size
    if width < 12 or height < 12:
        return image
    top = int(height * 0.78)
    bottom = height
    left = int(width * 0.05)
    right = int(width * 0.95)
    if bottom - top < 8:
        return image
    return image.crop((left, top, right, bottom))


def _upscale_if_small(image: Image.Image) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest < OCR_UPSCALE_MIN:
        scale = OCR_UPSCALE_MIN / float(longest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def _prepare_for_ocr(image: Image.Image, *, contrast: float = 1.35) -> Image.Image:
    image = _upscale_if_small(image.convert("RGB"))
    image = image.filter(ImageFilter.SHARPEN)
    return ImageEnhance.Contrast(image).enhance(contrast)


def _extract_size_tokens(text: str) -> list[str]:
    return [match.group(0).strip() for match in SIZE_TOKEN_PATTERN.finditer(text)]


def _enrich_text_for_matching(text: str) -> str:
    sizes = _extract_size_tokens(text)
    if not sizes:
        return text
    extra = " ".join(dict.fromkeys(sizes))
    if extra.lower() in text.lower():
        return text
    return f"{text} {extra}"


def _paddle_languages() -> list[str]:
    default = "en" if OCR_FAST_MODE else "en,hi"
    raw = os.getenv("OCR_LANGUAGES", default)
    langs = [part.strip() for part in raw.split(",") if part.strip()]
    return langs or ["en"]


def _init_paddle_for_lang(lang: str) -> Any | None:
    global _paddle_init_error
    if lang in _paddle_ocr_by_lang:
        return _paddle_ocr_by_lang[lang]
    try:
        os.environ["FLAGS_use_mkldnn"] = "0"
        from paddleocr import PaddleOCR

        base_kwargs: dict[str, Any] = {
            "use_angle_cls": True,
            "lang": lang,
            "use_gpu": False,
            "show_log": False,
            "det_db_thresh": 0.25,
            "det_db_unclip_ratio": OCR_DET_DB_UNCLIP_RATIO,
            "rec_batch_num": 8,
        }
        if OCR_PADDLE_REC_MODEL == "server":
            base_kwargs["ocr_version"] = "PP-OCRv4"
        if OCR_PADDLE_REC_MODEL_DIR and OCR_PADDLE_REC_MODEL in {"custom", "server", "mobile"}:
            base_kwargs["rec_model_dir"] = OCR_PADDLE_REC_MODEL_DIR
        try:
            engine = PaddleOCR(**base_kwargs, enable_mkldnn=False)
        except TypeError:
            try:
                engine = PaddleOCR(**base_kwargs)
            except TypeError:
                base_kwargs.pop("ocr_version", None)
                base_kwargs.pop("det_db_unclip_ratio", None)
                base_kwargs.pop("rec_model_dir", None)
                engine = PaddleOCR(**base_kwargs)
        _paddle_ocr_by_lang[lang] = engine
        _paddle_init_error = None
        print(f"PaddleOCR ready (lang={lang}, model={OCR_PADDLE_REC_MODEL})")
        return engine
    except Exception as exc:
        _paddle_init_error = str(exc)
        print(f"PaddleOCR unavailable for lang={lang}: {exc}")
        return None


def _init_paddle() -> Any | None:
    global _paddle_ocr, _paddle_init_error
    if _paddle_ocr is not None:
        return _paddle_ocr
    for lang in _paddle_languages():
        engine = _init_paddle_for_lang(lang)
        if engine is not None:
            _paddle_ocr = engine
            return _paddle_ocr
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
    if preference == "easyocr":
        order = ["easyocr", "paddle"]
    else:
        order = ["paddle", "easyocr"]

    for engine in order:
        reader = _init_paddle() if engine == "paddle" else _init_easyocr()
        if reader is not None:
            _active_engine = engine
            return _active_engine

    _active_engine = None
    print("No OCR engine available — OCR step disabled.")
    return None


def _line_confidence_ok(text: str, conf: float, *, relaxed: bool = False) -> bool:
    token = re.sub(r"[^a-zA-Z0-9]", "", text)
    short_min = max(0.22, OCR_SHORT_WORD_MIN_CONFIDENCE - (0.07 if relaxed else 0.0))
    line_min = max(0.35, OCR_LINE_MIN_CONFIDENCE - (0.08 if relaxed else 0.0))
    if len(token) <= 5:
        return conf >= short_min
    return conf >= line_min


def pil_from_bbox(
    source_image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    padding: float | None = None,
) -> Image.Image:
    """Re-crop a facing from the full-resolution shelf image (no JPEG round-trip)."""
    import cv2

    pad = OCR_CROP_PADDING if padding is None else padding
    height, width = source_image.shape[:2]
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = int(box_w * pad)
    pad_y = int(box_h * pad)
    nx1 = max(0, x1 - pad_x)
    ny1 = max(0, y1 - pad_y)
    nx2 = min(width, x2 + pad_x)
    ny2 = min(height, y2 + pad_y)
    crop = source_image[ny1:ny2, nx1:nx2]
    if crop.size == 0:
        crop = source_image[max(0, y1) : min(height, y2), max(0, x1) : min(width, x2)]
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def load_facing_image(record: dict, source_image: np.ndarray | None = None) -> Image.Image:
    if source_image is not None:
        return pil_from_bbox(
            source_image,
            int(record["x1"]),
            int(record["y1"]),
            int(record["x2"]),
            int(record["y2"]),
        )
    from PIL import Image as PILImage

    return PILImage.open(record["image_path"]).convert("RGB")


def _parse_paddle_lines(result: Any, *, relaxed: bool) -> tuple[str, float, list[float]]:
    lines: list[str] = []
    confidences: list[float] = []
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
            if text.strip() and _line_confidence_ok(text, conf, relaxed=relaxed):
                lines.append(text.strip())
                confidences.append(conf)
    merged = " ".join(lines)
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return merged, mean_conf, confidences


def _postprocess_ocr_text(text: str) -> str:
    from app.ocr_spell_correct import enrich_ocr_with_catalog_phrases

    return enrich_ocr_with_catalog_phrases(_clean_ocr_text(text))


def _read_with_paddle(
    arr: np.ndarray,
    *,
    relaxed: bool = False,
    rec_only: bool = False,
) -> tuple[str, float]:
    langs = _paddle_languages() if OCR_MULTILANG_MERGE else [_paddle_languages()[0]]
    best_text = ""
    best_conf = 0.0

    for lang in langs:
        ocr = _init_paddle_for_lang(lang)
        if ocr is None:
            continue
        try:
            if rec_only:
                try:
                    result = ocr.ocr(arr, det=False, rec=True, cls=True)
                except TypeError:
                    result = ocr.ocr(arr, cls=True)
            else:
                result = ocr.ocr(arr, cls=True)
        except Exception as exc:
            print(f"PaddleOCR read failed ({lang}): {exc}")
            continue
        text, conf, _ = _parse_paddle_lines(result, relaxed=relaxed)
        if conf > best_conf or (conf == best_conf and len(text) > len(best_text)):
            best_text, best_conf = text, conf

    return best_text, best_conf


def _read_with_easyocr(arr: np.ndarray, *, relaxed: bool = False) -> tuple[str, float]:
    reader = _init_easyocr()
    if reader is None:
        return "", 0.0
    try:
        detailed = reader.readtext(arr, detail=1, paragraph=False)
        lines: list[str] = []
        confidences: list[float] = []
        for item in detailed or []:
            if not item or len(item) < 3:
                continue
            text, conf = str(item[1]), float(item[2])
            if text.strip() and _line_confidence_ok(text, conf, relaxed=relaxed):
                lines.append(text.strip())
                confidences.append(conf)
        if lines:
            merged = " ".join(lines)
            return merged, sum(confidences) / len(confidences)
        fallback = reader.readtext(arr, detail=0, paragraph=True)
        if isinstance(fallback, list):
            merged = " ".join(str(line) for line in fallback if line)
            return merged, 0.45 if merged.strip() else 0.0
        merged = str(fallback or "")
        return merged, 0.45 if merged.strip() else 0.0
    except Exception as exc:
        print(f"EasyOCR read failed: {exc}")
        return "", 0.0


def _text_richness(text: str) -> float:
    cleaned = text.strip()
    if not cleaned:
        return 0.0
    tokens = cleaned.split()
    alpha_ratio = sum(ch.isalnum() for ch in cleaned) / max(len(cleaned), 1)
    return min(1.0, len(tokens) / 8.0) * alpha_ratio


def _catalog_score(text: str, scan_context: dict | None) -> float:
    if len(text.strip()) < 3:
        return 0.0
    enriched = _enrich_text_for_matching(normalize_ocr_text(text))
    product = match_from_text(enriched, scan_context=scan_context)
    if not product:
        return 0.0
    return float(product.get("confidence") or 0.0)


def score_ocr_candidate(
    text: str,
    ocr_confidence: float,
    scan_context: dict | None = None,
) -> tuple[float, float]:
    catalog = _catalog_score(text, scan_context)
    richness = _text_richness(text)
    final = 0.5 * ocr_confidence + 0.4 * catalog + 0.1 * richness
    return final, catalog


def _read_variant(
    variant: OcrVariant,
    *,
    relaxed: bool = False,
    rec_only: bool = False,
) -> tuple[str, float]:
    engine = _resolve_engine()
    if engine is None:
        return "", 0.0
    arr = variant.image
    if engine == "paddle":
        return _read_with_paddle(arr, relaxed=relaxed, rec_only=rec_only)
    return _read_with_easyocr(arr, relaxed=relaxed)


def _run_multipass_on_crop(
    crop: Image.Image,
    *,
    scan_context: dict | None,
    heavy: bool,
    rec_only: bool = False,
) -> OcrReadResult:
    variants = build_ocr_variants(crop, heavy=heavy)
    best = OcrReadResult(text="", confidence=0.0, variant="", catalog_score=0.0, score=0.0, attempts=0)
    relaxed = heavy

    for variant in variants:
        text, ocr_conf = _read_variant(variant, relaxed=relaxed, rec_only=rec_only)
        text = _postprocess_ocr_text(text)
        if not text:
            continue
        score, catalog = score_ocr_candidate(text, ocr_conf, scan_context)
        candidate = OcrReadResult(
            text=text,
            confidence=round(ocr_conf, 4),
            variant=variant.name,
            catalog_score=round(catalog, 4),
            score=round(score, 4),
            attempts=1,
        )
        if score > best.score or (score == best.score and len(text) > len(best.text)):
            best = candidate

    best.attempts = len(variants)
    return best


def read_text_from_pil(image: Image.Image, scan_context: dict | None = None) -> str:
    return read_packaging_text_result(image, scan_context=scan_context).text


def active_ocr_engine() -> str | None:
    return _resolve_engine()


def ocr_engine_status() -> dict:
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
        "ocr_paddle_rec_model": OCR_PADDLE_REC_MODEL,
        "ocr_languages": _paddle_languages(),
        "ocr_fast_mode": OCR_FAST_MODE,
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


def _merge_results(*results: OcrReadResult) -> OcrReadResult:
    text = _merge_ocr_texts(*(r.text for r in results if r.text))
    if not text:
        return OcrReadResult(text="", confidence=0.0, variant="", catalog_score=0.0, score=0.0, attempts=0)
    best = max(results, key=lambda r: (r.score, len(r.text)))
    confidences = [r.confidence for r in results if r.confidence > 0]
    mean_conf = sum(confidences) / len(confidences) if confidences else best.confidence
    score, catalog = score_ocr_candidate(text, mean_conf, scan_context=None)
    return OcrReadResult(
        text=text,
        confidence=round(mean_conf, 4),
        variant=best.variant or "merged",
        catalog_score=round(catalog, 4),
        score=round(score, 4),
        attempts=sum(r.attempts for r in results),
    )


def read_packaging_text_result(
    image: Image.Image,
    *,
    scan_context: dict | None = None,
    heavy: bool = False,
) -> OcrReadResult:
    """Multi-band, multi-variant OCR with confidence + catalog scoring."""
    if not OCR_ENABLED:
        return OcrReadResult(text="", confidence=0.0, variant="", catalog_score=0.0, score=0.0)

    width, height = image.size
    if max(width, height) < 160 and not heavy:
        heavy = True

    pack_bottom = max(1, int(height * 0.85))
    pack_crop = image.crop((0, 0, width, pack_bottom))

    def _read_band(crop: Image.Image, *, band_rec_only: bool = False) -> OcrReadResult:
        use_rec_only = band_rec_only and OCR_REC_ONLY_BANDS and _resolve_engine() == "paddle"
        return _run_multipass_on_crop(
            crop,
            scan_context=scan_context,
            heavy=heavy,
            rec_only=use_rec_only,
        )

    logo_band = logo_focus_crop(pack_crop)
    flavor_band = flavor_focus_crop(pack_crop)
    center_band = center_logo_crop(pack_crop)
    edge_band = shelf_edge_crop(pack_crop)
    if OCR_FAST_MODE and not heavy:
        band_results = [
            _read_band(edge_band, band_rec_only=True),
            _read_band(center_band, band_rec_only=True),
            _read_band(logo_band, band_rec_only=True),
            _read_band(flavor_band, band_rec_only=True),
            _read_band(pack_crop),
        ]
    else:
        band_results = [
            _read_band(logo_band, band_rec_only=True),
            _read_band(flavor_band, band_rec_only=True),
            _read_band(pack_crop),
        ]

        if pack_bottom >= 40:
            band_h = max(1, int(pack_bottom * 0.45))
            top_band = pack_crop.crop((0, 0, width, band_h))
            center_top = max(1, int(pack_bottom * 0.2))
            center_bottom = min(pack_bottom, int(pack_bottom * 0.65))
            center_band = pack_crop.crop((0, center_top, width, center_bottom))
            band_results.extend([_read_band(top_band, band_rec_only=True), _read_band(center_band)])

    merged = _merge_results(*band_results)
    if merged.text:
        post = _postprocess_ocr_text(merged.text)
        score, catalog = score_ocr_candidate(
            post,
            merged.confidence,
            scan_context,
        )
        merged = OcrReadResult(
            text=post,
            confidence=merged.confidence,
            variant=merged.variant,
            catalog_score=round(catalog, 4),
            score=round(score, 4),
            attempts=merged.attempts,
        )
    return merged


def _ocr_needs_heavy_retry(result: OcrReadResult, scan_context: dict | None = None) -> bool:
    """Decide whether to run heavy preprocessing + extra OCR bands."""
    text = (result.text or "").strip()
    if len(text) < 3:
        return True
    if result.confidence < OCR_LOW_CONFIDENCE:
        return True
    if result.catalog_score < 0.35:
        return True
    enriched = _enrich_text_for_matching(normalize_ocr_text(text))
    if match_from_text(enriched, scan_context=scan_context) is None:
        return True
    return False


def read_packaging_text_max_effort(
    image: Image.Image,
    *,
    scan_context: dict | None = None,
) -> OcrReadResult:
    """Last-resort OCR for unknown facings: heavy preprocess + all bands."""
    return read_packaging_text_result(image, scan_context=scan_context, heavy=True)


def read_packaging_text_tiered(
    image: Image.Image,
    *,
    scan_context: dict | None = None,
) -> OcrReadResult:
    """Standard multi-pass OCR; heavy preprocessing when text is weak or unmatched."""
    result = read_packaging_text_result(image, scan_context=scan_context, heavy=False)
    needs_heavy = _ocr_needs_heavy_retry(result, scan_context)
    if needs_heavy:
        heavy = read_packaging_text_result(image, scan_context=scan_context, heavy=True)
        if heavy.score >= result.score or len(heavy.text.strip()) > len(result.text.strip()):
            return heavy
    return result


def read_packaging_text(
    image: Image.Image,
    *,
    aggressive: bool = False,
    scan_context: dict | None = None,
) -> str:
    """Backward-compatible text-only API."""
    return read_packaging_text_result(
        image,
        scan_context=scan_context,
        heavy=aggressive,
    ).text


def classify_with_ocr(
    image: Image.Image,
    raw_text: str | None = None,
    scan_context: dict | None = None,
) -> dict | None:
    if not OCR_ENABLED:
        return None
    raw = _clean_ocr_text(
        raw_text if raw_text is not None else read_packaging_text_result(image, scan_context=scan_context).text
    )
    raw = normalize_ocr_text(raw)
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


def combined_facing_confidence(yolo_conf: float, ocr_conf: float, catalog_score: float) -> float:
    """Blend detection, OCR, and catalog agreement into one facing confidence."""
    yolo = max(0.0, min(1.0, float(yolo_conf or 0)))
    ocr = max(0.0, min(1.0, float(ocr_conf or 0)))
    catalog = max(0.0, min(1.0, float(catalog_score or 0)))
    if ocr <= 0 and catalog <= 0:
        return round(yolo * 0.85, 4)
    return round(min(yolo, max(ocr, catalog * 0.95)) * (0.65 + 0.35 * catalog), 4)
