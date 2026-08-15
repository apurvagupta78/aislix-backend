"""Build OCR input variants from YOLO product crops (padding handled upstream)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

OCR_UPSCALE_MIN = int(os.getenv("OCR_UPSCALE_MIN", "480"))
OCR_UPSCALE_FACTOR = float(os.getenv("OCR_UPSCALE_FACTOR", "2.0"))
OCR_TARGET_TEXT_HEIGHT = int(os.getenv("OCR_TARGET_TEXT_HEIGHT", "36"))
OCR_DESKEW_MIN_DEG = float(os.getenv("OCR_DESKEW_MIN_DEG", "3.0"))
OCR_VARIANT_DENOISE = os.getenv("OCR_VARIANT_DENOISE", "true").lower() in {"1", "true", "yes"}
OCR_PERSPECTIVE = os.getenv("OCR_PERSPECTIVE", "true").lower() in {"1", "true", "yes"}
OCR_SUPER_RES_FACTOR = float(os.getenv("OCR_SUPER_RES_FACTOR", "3.0"))
OCR_SUPER_RES_MIN = int(os.getenv("OCR_SUPER_RES_MIN", "1280"))
OCR_FULL_MODE = os.getenv("OCR_FULL_MODE", "false").lower() in {"1", "true", "yes"}
OCR_FAST_MODE = os.getenv("OCR_FAST_MODE", "true").lower() in {"1", "true", "yes"} and not OCR_FULL_MODE


@dataclass(frozen=True)
class OcrVariant:
    name: str
    image: np.ndarray  # RGB uint8


def pil_to_rgb_np(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    if rgb.ndim != 3:
        raise ValueError("Expected RGB image.")
    return rgb


def rgb_np_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.asarray(arr, dtype=np.uint8))


def _upscale_np(rgb: np.ndarray, *, factor: float | None = None, min_longest: int | None = None) -> np.ndarray:
    h, w = rgb.shape[:2]
    scale = 1.0
    if factor and factor > 1.0:
        scale = max(scale, factor)
    longest = max(h, w)
    if min_longest and longest < min_longest:
        scale = max(scale, min_longest / float(longest))
    if scale <= 1.01:
        return rgb
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def apply_clahe(rgb: np.ndarray) -> np.ndarray:
    """Local contrast enhancement for glare / uneven shelf lighting."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    merged = cv2.merge([l_channel, a_channel, b_channel])
    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


def apply_sharpen_contrast(rgb: np.ndarray, *, contrast: float = 1.45) -> np.ndarray:
    pil = rgb_np_to_pil(rgb)
    from PIL import ImageEnhance, ImageFilter

    pil = pil.filter(ImageFilter.SHARPEN)
    pil = ImageEnhance.Contrast(pil).enhance(contrast)
    return pil_to_rgb_np(pil)


def apply_denoise_adaptive_threshold(rgb: np.ndarray) -> np.ndarray:
    """Denoise + adaptive binarization inverted back to RGB for OCR engines."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if OCR_VARIANT_DENOISE:
        gray = cv2.fastNlMeansDenoising(gray, h=8, templateWindowSize=7, searchWindowSize=21)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)


def deskew_if_needed(rgb: np.ndarray) -> np.ndarray:
    """Straighten slightly rotated pack text using minAreaRect."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(mask)
    if coords is None or len(coords) < 20:
        return rgb
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < OCR_DESKEW_MIN_DEG:
        return rgb
    h, w = rgb.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        rgb, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def correct_perspective(rgb: np.ndarray) -> np.ndarray:
    """Warp angled pack face to a frontal rectangle when a quad is detected."""
    h, w = rgb.shape[:2]
    if h < 48 or w < 48:
        return rgb

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 140)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return rgb

    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    if area < 0.12 * h * w:
        return rgb

    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    if len(approx) != 4:
        return rgb

    pts = _order_quad_points(approx.reshape(4, 2).astype(np.float32))
    width_a = np.linalg.norm(pts[1] - pts[0])
    width_b = np.linalg.norm(pts[2] - pts[3])
    height_a = np.linalg.norm(pts[3] - pts[0])
    height_b = np.linalg.norm(pts[2] - pts[1])
    max_w = int(max(width_a, width_b))
    max_h = int(max(height_a, height_b))
    if max_w < 24 or max_h < 24:
        return rgb

    dst = np.array(
        [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(pts, dst)
    warped = cv2.warpPerspective(rgb, matrix, (max_w, max_h), flags=cv2.INTER_CUBIC)
    return warped


def apply_gamma(rgb: np.ndarray, gamma: float = 0.75) -> np.ndarray:
    """Brighten dark bottle/carton crops."""
    inv = 1.0 / max(gamma, 0.01)
    table = np.array([((i / 255.0) ** inv) * 255 for i in range(256)]).astype("uint8")
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    corrected = cv2.LUT(bgr, table)
    return cv2.cvtColor(corrected, cv2.COLOR_BGR2RGB)


def apply_super_resolution(rgb: np.ndarray) -> np.ndarray:
    """High-quality upscale + unsharp mask (lightweight super-resolution)."""
    upscaled = _upscale_np(
        rgb,
        factor=OCR_SUPER_RES_FACTOR,
        min_longest=max(OCR_SUPER_RES_MIN, OCR_UPSCALE_MIN),
    )
    blurred = cv2.GaussianBlur(upscaled, (0, 0), sigmaX=1.2)
    sharpened = cv2.addWeighted(upscaled, 1.55, blurred, -0.55, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def build_ocr_variants(
    image: Image.Image,
    *,
    heavy: bool = False,
    fast: bool | None = None,
) -> list[OcrVariant]:
    """
    Produce OCR-ready RGB variants from a product crop.
    Standard: original+upscale, 2x, CLAHE, sharpen.
    Fast (default on Railway): original, CLAHE, sharpen — skips super-res and extra bands.
    Heavy: adds deskew + adaptive threshold (for tiered retry).
    """
    use_fast = OCR_FAST_MODE if fast is None else fast
    base = pil_to_rgb_np(image)
    base = _upscale_np(base, min_longest=OCR_UPSCALE_MIN)
    if OCR_PERSPECTIVE and not use_fast:
        base = correct_perspective(base)

    if use_fast and not heavy:
        variants: list[OcrVariant] = [
            OcrVariant("original", base),
            OcrVariant("clahe", apply_clahe(base)),
            OcrVariant("sharpen", apply_sharpen_contrast(base)),
        ]
    elif use_fast and heavy:
        variants = [
            OcrVariant("original", base),
            OcrVariant("clahe", apply_clahe(base)),
            OcrVariant("sharpen", apply_sharpen_contrast(base)),
            OcrVariant("adaptive_thresh", apply_denoise_adaptive_threshold(base)),
        ]
    else:
        variants = [
            OcrVariant("original", base),
            OcrVariant("upscale_2x", _upscale_np(base, factor=OCR_UPSCALE_FACTOR)),
            OcrVariant("clahe", apply_clahe(base)),
            OcrVariant("sharpen", apply_sharpen_contrast(base)),
            OcrVariant("super_res", apply_super_resolution(base)),
        ]

    if heavy and not use_fast:
        deskewed = deskew_if_needed(base)
        perspective = correct_perspective(base) if OCR_PERSPECTIVE else base
        variants.extend(
            [
                OcrVariant("perspective", perspective),
                OcrVariant("perspective_clahe", apply_clahe(perspective)),
                OcrVariant("gamma", apply_gamma(base)),
                OcrVariant("deskew", deskewed),
                OcrVariant("deskew_clahe", apply_clahe(deskewed)),
                OcrVariant("adaptive_thresh", apply_denoise_adaptive_threshold(base)),
                OcrVariant(
                    "heavy_upscale",
                    _upscale_np(base, min_longest=max(OCR_SUPER_RES_MIN, OCR_UPSCALE_MIN * 2)),
                ),
            ]
        )

    seen: set[tuple[int, int, str]] = set()
    unique: list[OcrVariant] = []
    for variant in variants:
        h, w = variant.image.shape[:2]
        key = (h, w, variant.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(variant)
    return unique
