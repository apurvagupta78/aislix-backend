"""Tests for high-res OCR crops and snack row recovery."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.ocr_reader import flavor_focus_crop, load_facing_image, pil_from_bbox
from app.recognizer import _is_generic_lays_faiss_match
from app.scan_context import resolve_scan_context
from app.snack_row_recovery import (
    _bag_color_family,
    recover_snack_variants_by_row,
    should_use_snack_row_recovery,
)


def test_pil_from_bbox_uses_full_resolution_with_padding():
    source = np.zeros((400, 300, 3), dtype=np.uint8)
    source[100:200, 50:150, :] = 255
    crop = pil_from_bbox(source, 50, 100, 150, 200, padding=0.1)
    assert crop.size[0] >= 100
    assert crop.size[1] >= 100


def test_load_facing_image_prefers_source_over_jpeg_path(tmp_path):
    source = np.full((200, 200, 3), 128, dtype=np.uint8)
    source[40:160, 40:160, 2] = 255  # BGR red channel
    record = {"x1": 40, "y1": 40, "x2": 160, "y2": 160, "image_path": str(tmp_path / "missing.jpg")}
    img = load_facing_image(record, source)
    assert img.size[0] >= 120
    assert img.size[1] >= 120
    assert img.getpixel((60, 60))[0] == 255


def test_flavor_focus_crop_is_narrower_than_logo_band():
    img = Image.new("RGB", (100, 200), color=(255, 255, 255))
    flavor = flavor_focus_crop(img)
    assert flavor.size[1] < 200


def test_generic_lays_faiss_blocked_without_flavor_ocr():
    match = {
        "brand": "Lays",
        "product_name": "Classic Salted Potato Chips",
        "sku": "lays_classic_salted_potato_chips",
    }
    assert _is_generic_lays_faiss_match(match, "Lay's Potato Chips") is True
    assert _is_generic_lays_faiss_match(match, "Lay's Magic Masala") is False


def test_bag_color_orange_red_green():
    record = {"x1": 0, "y1": 0, "x2": 80, "y2": 120}

    blue_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    blue_bgr[:, :, 0] = 140  # B channel in BGR — Magic Masala teal with warm tone
    blue_bgr[:, :, 1] = 90
    blue_bgr[:, :, 2] = 100
    assert _bag_color_family(blue_bgr, record) == "blue"

    orange_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    orange_bgr[:, :, 2] = 200
    orange_bgr[:, :, 1] = 120
    orange_bgr[:, :, 0] = 40
    assert _bag_color_family(orange_bgr, record) == "orange"

    red_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    red_bgr[:, :, 2] = 200
    red_bgr[:, :, 1] = 30
    red_bgr[:, :, 0] = 30
    assert _bag_color_family(red_bgr, record) == "red"

    green_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    green_bgr[:, :, 0] = 90
    green_bgr[:, :, 1] = 150
    green_bgr[:, :, 2] = 40
    assert _bag_color_family(green_bgr, record) == "green"

    tomato_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    tomato_bgr[:, :, 0] = 160  # cool dark blue Tomato Tango pack
    tomato_bgr[:, :, 1] = 50
    tomato_bgr[:, :, 2] = 55
    assert _bag_color_family(tomato_bgr, record) == "red"

    blue_cast_green = np.zeros((120, 80, 3), dtype=np.uint8)
    blue_cast_green[:, :, 0] = 120  # B high — blue photo cast
    blue_cast_green[:, :, 1] = 105
    blue_cast_green[:, :, 2] = 85
    assert _bag_color_family(blue_cast_green, record) == "green"


def test_snack_row_recovery_overrides_wrong_magic_masala_on_green_row():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((600, 400, 3), dtype=np.uint8)
    source[50:150, 20:380, 2] = 200
    source[50:150, 20:380, 1] = 120
    source[50:150, 20:380, 0] = 40
    source[350:450, 20:380, 0] = 120
    source[350:450, 20:380, 1] = 105
    source[350:450, 20:380, 2] = 85

    classified = [
        {
            "x1": 20,
            "y1": 50,
            "x2": 80,
            "y2": 150,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
        },
        {
            "x1": 20,
            "y1": 350,
            "x2": 80,
            "y2": 450,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.84,
        },
        {
            "x1": 100,
            "y1": 355,
            "x2": 160,
            "y2": 445,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.84,
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx)
    assert stats["snack_row_recovery"] >= 2
    green_row = [r for r in updated if r["y1"] > 300]
    assert len(green_row) == 2
    assert all(
        row["product_name"] == "American Style Cream and Onion Potato Chips" for row in green_row
    )


def test_snack_row_recovery_assigns_unknowns_by_row():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((600, 400, 3), dtype=np.uint8)
    # top row orange (BGR)
    source[50:150, 20:380, 2] = 200
    source[50:150, 20:380, 1] = 120
    source[50:150, 20:380, 0] = 40
    # bottom row green (BGR)
    source[350:450, 20:380, 2] = 40
    source[350:450, 20:380, 1] = 150
    source[350:450, 20:380, 0] = 90

    classified = [
        {"x1": 20, "y1": 50, "x2": 80, "y2": 150, "brand": "Unknown", "product_name": "Unidentified SKU", "confidence": 0.35},
        {"x1": 100, "y1": 55, "x2": 160, "y2": 145, "brand": "Unknown", "product_name": "Unidentified SKU", "confidence": 0.35},
        {"x1": 20, "y1": 350, "x2": 80, "y2": 450, "brand": "Unknown", "product_name": "Unidentified SKU", "confidence": 0.35},
        {"x1": 100, "y1": 355, "x2": 160, "y2": 445, "brand": "Unknown", "product_name": "Unidentified SKU", "confidence": 0.35},
    ]
    assert should_use_snack_row_recovery(classified, ctx)
    updated, stats = recover_snack_variants_by_row(classified, source, ctx)
    assert stats["snack_row_recovery"] >= 2
    products = {(row["product_name"]) for row in updated}
    assert "Indias Magic Masala Potato Chips" in products
    assert "American Style Cream and Onion Potato Chips" in products
