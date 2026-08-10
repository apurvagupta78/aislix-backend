"""Detect single-row vs multi-row shelf layout from YOLO box geometry."""

from __future__ import annotations

from typing import Literal

Layout = Literal["single_row", "multi_row"]


def _box_y_stats(box) -> tuple[float, float]:
    if isinstance(box, dict):
        y1, y2 = float(box["y1"]), float(box["y2"])
    else:
        y1, y2 = float(box[1]), float(box[3])
    height = max(0.0, y2 - y1)
    center = (y1 + y2) / 2.0
    return center, height


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
