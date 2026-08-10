"""Detect shelf layout: full rack (multi-row), wide single row, or close-up single bin."""

from __future__ import annotations

from typing import Literal

Layout = Literal["single_row", "multi_row"]
ShelfMode = Literal["single_bin", "single_row", "multi_row"]


def _box_y_stats(box) -> tuple[float, float]:
    if isinstance(box, dict):
        y1, y2 = float(box["y1"]), float(box["y2"])
    else:
        y1, y2 = float(box[1]), float(box[3])
    height = max(0.0, y2 - y1)
    center = (y1 + y2) / 2.0
    return center, height


def _box_width(box) -> float:
    if isinstance(box, dict):
        return max(0.0, float(box["x2"]) - float(box["x1"]))
    return max(0.0, float(box[2]) - float(box[0]))


def detect_layout(boxes: list, image_h: int) -> Layout:
    """Classify shelf as one horizontal row or multiple stacked rows."""
    if len(boxes) < 2:
        return "single_row"

    y_centers: list[float] = []
    heights: list[float] = []
    for box in boxes:
        center, height = _box_y_stats(box)
        if height > 0:
            y_centers.append(center)
            heights.append(height)

    if not y_centers:
        return "multi_row"

    heights.sort()
    median_h = heights[len(heights) // 2]
    y_spread = max(y_centers) - min(y_centers)
    band_center = sum(y_centers) / len(y_centers)
    band_tol = median_h * 0.65
    in_band = sum(1 for yc in y_centers if abs(yc - band_center) <= band_tol)
    band_ratio = in_band / len(y_centers)

    if band_ratio >= 0.70 and y_spread <= median_h * 2.5:
        return "single_row"

    if len(boxes) <= 18 and y_spread <= max(image_h * 0.35, median_h * 3.0) and band_ratio >= 0.65:
        return "single_row"

    return "multi_row"


def detect_shelf_mode(boxes: list, image_h: int, image_w: int) -> ShelfMode:
    """
    Distinguish a close-up photo of one shelf bin (8 bottles filling the frame)
    from a single row on a full rack (many small facings) or a multi-row rack.
    """
    layout = detect_layout(boxes, image_h)
    if layout == "multi_row":
        return "multi_row"

    heights = sorted(_box_y_stats(box)[1] for box in boxes if _box_y_stats(box)[1] > 0)
    if not heights:
        return "single_row"

    median_h = heights[len(heights) // 2]
    median_w = sorted(_box_width(b) for b in boxes if _box_width(b) > 0)
    median_w = median_w[len(median_w) // 2] if median_w else 0.0

    # Close-up bin: large facings and/or YOLO over-segmentation (cap + body splits).
    bottles_fill_frame = median_h >= image_h * 0.16
    over_segmented = len(boxes) >= 9
    wide_bottles = median_w >= image_w * 0.06

    if bottles_fill_frame or (over_segmented and wide_bottles):
        return "single_bin"

    return "single_row"
