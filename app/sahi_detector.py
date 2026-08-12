"""Slicing-aided (SAHI-style) YOLO inference for dense phone shelf photos."""

from __future__ import annotations

import os

import numpy as np

from app.detector import YOLO_DEDUP_IOU, deduplicate_boxes, detect_products, get_boxes

SAHI_TILE_SIZE = int(os.getenv("SAHI_TILE_SIZE", "640"))
SAHI_OVERLAP_RATIO = float(os.getenv("SAHI_OVERLAP_RATIO", "0.25"))
SAHI_INCLUDE_FULL_FRAME = os.getenv("SAHI_INCLUDE_FULL_FRAME", "true").lower() in {
    "1",
    "true",
    "yes",
}


def generate_slice_windows(
    image_h: int,
    image_w: int,
    *,
    tile_size: int | None = None,
    overlap_ratio: float | None = None,
) -> list[tuple[int, int, int, int]]:
    """Return (x1, y1, x2, y2) windows covering the image with overlap."""
    tile_size = tile_size or SAHI_TILE_SIZE
    overlap_ratio = overlap_ratio if overlap_ratio is not None else SAHI_OVERLAP_RATIO
    if image_h <= tile_size and image_w <= tile_size:
        return [(0, 0, image_w, image_h)]

    stride = max(1, int(tile_size * (1.0 - overlap_ratio)))
    windows: list[tuple[int, int, int, int]] = []
    y = 0
    while True:
        y2 = min(y + tile_size, image_h)
        y1 = max(0, y2 - tile_size)
        x = 0
        while True:
            x2 = min(x + tile_size, image_w)
            x1 = max(0, x2 - tile_size)
            windows.append((x1, y1, x2, y2))
            if x2 >= image_w:
                break
            x += stride
        if y2 >= image_h:
            break
        y += stride

    # Deduplicate identical windows when image is smaller than stride.
    unique: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for window in windows:
        if window not in seen:
            seen.add(window)
            unique.append(window)
    return unique


def _detect_on_crop(
    image: np.ndarray,
    window: tuple[int, int, int, int],
    *,
    conf: float,
) -> list[np.ndarray]:
    x1, y1, x2, y2 = window
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return []
    results, pad_x = detect_products(crop, conf=conf)
    local_boxes = get_boxes(results, pad_x=pad_x, max_x=crop.shape[1])
    shifted: list[np.ndarray] = []
    for box in local_boxes:
        full = box.copy()
        full[0] += x1
        full[2] += x1
        full[1] += y1
        full[3] += y1
        shifted.append(full)
    return shifted


def detect_products_sahi(
    image: np.ndarray,
    *,
    conf: float | None = None,
    tile_size: int | None = None,
    overlap_ratio: float | None = None,
) -> tuple[list[np.ndarray], dict]:
    """Run YOLO on overlapping tiles + optional full frame; merge with dedup."""
    from app.detector import YOLO_CONF_THRESHOLD

    conf = conf if conf is not None else YOLO_CONF_THRESHOLD
    image_h, image_w = image.shape[:2]
    all_boxes: list[np.ndarray] = []
    stats = {
        "sahi_enabled": True,
        "sahi_tile_size": tile_size or SAHI_TILE_SIZE,
        "sahi_overlap_ratio": overlap_ratio if overlap_ratio is not None else SAHI_OVERLAP_RATIO,
        "sahi_slice_count": 0,
    }

    if SAHI_INCLUDE_FULL_FRAME:
        results, pad_x = detect_products(image, conf=conf)
        all_boxes.extend(get_boxes(results, pad_x=pad_x, max_x=image_w))

    windows = generate_slice_windows(
        image_h,
        image_w,
        tile_size=tile_size,
        overlap_ratio=overlap_ratio,
    )
    stats["sahi_slice_count"] = len(windows)

    for window in windows:
        all_boxes.extend(_detect_on_crop(image, window, conf=conf))

    if not all_boxes:
        return [], stats

    dedup_iou = float(os.getenv("SAHI_DEDUP_IOU", str(YOLO_DEDUP_IOU)))
    merged = deduplicate_boxes(all_boxes, iou_threshold=dedup_iou)
    stats["sahi_raw_boxes"] = len(all_boxes)
    stats["sahi_merged_boxes"] = len(merged)
    return merged, stats


def detection_mode_enabled() -> bool:
    mode = os.getenv("DETECTION_MODE", "standard").strip().lower()
    return mode in {"sahi", "sliced", "tiling"}


def run_detection(
    image: np.ndarray,
    *,
    conf: float | None = None,
) -> tuple[list[np.ndarray], dict]:
    """Standard or SAHI detection based on DETECTION_MODE env."""
    if detection_mode_enabled():
        return detect_products_sahi(image, conf=conf)
    results, pad_x = detect_products(image, conf=conf)
    boxes = get_boxes(results, pad_x=pad_x, max_x=image.shape[1])
    return boxes, {"sahi_enabled": False, "detection_mode": "standard"}
