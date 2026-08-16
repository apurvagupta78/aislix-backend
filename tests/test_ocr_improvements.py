"""Tests for high-res OCR crops and snack row recovery."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.ocr_reader import flavor_focus_crop, load_facing_image, pil_from_bbox
from app.recognizer import _is_generic_lays_faiss_match
from app.scan_context import resolve_scan_context
from app.snack_row_recovery import (
    _bag_color_family,
    finalize_lays_rack_labels,
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
    assert _bag_color_family(orange_bgr, record) == "red"

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

    blue_cast_green = np.zeros((120, 80, 3), dtype=np.uint8)
    blue_cast_green[:, :, 0] = 120  # B high — blue photo cast
    blue_cast_green[:, :, 1] = 105
    blue_cast_green[:, :, 2] = 85
    assert _bag_color_family(blue_cast_green, record) == "green"

    tomato_bgr = np.zeros((120, 80, 3), dtype=np.uint8)
    tomato_bgr[:, :, 0] = 160  # cool blue Magic Masala pack under blue cast
    tomato_bgr[:, :, 1] = 50
    tomato_bgr[:, :, 2] = 55
    assert _bag_color_family(tomato_bgr, record) == "blue"

    cool_blue_tomato = np.zeros((120, 80, 3), dtype=np.uint8)
    cool_blue_tomato[:, :, 0] = 90
    cool_blue_tomato[:, :, 1] = 75
    cool_blue_tomato[:, :, 2] = 110
    assert _bag_color_family(cool_blue_tomato, record) == "blue"

    warm_lit_green = np.zeros((120, 80, 3), dtype=np.uint8)
    warm_lit_green[:, :, 0] = 80
    warm_lit_green[:, :, 1] = 100
    warm_lit_green[:, :, 2] = 115
    assert _bag_color_family(warm_lit_green, record) == "green"

    blue_cast_green2 = np.zeros((120, 80, 3), dtype=np.uint8)
    blue_cast_green2[:, :, 0] = 118  # BGR: cool cast on green pack
    blue_cast_green2[:, :, 1] = 98
    blue_cast_green2[:, :, 2] = 92
    assert _bag_color_family(blue_cast_green2, record) == "green"


def test_snack_row_recovery_overrides_tomato_on_green_row():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((600, 400, 3), dtype=np.uint8)
    source[50:150, 20:380, 2] = 200
    source[50:150, 20:380, 1] = 120
    source[50:150, 20:380, 0] = 40
    source[450:550, 20:380, 0] = 115
    source[450:550, 20:380, 1] = 100
    source[450:550, 20:380, 2] = 80

    classified = [
        {"x1": 20, "y1": 50, "x2": 80, "y2": 150, "brand": "Lays", "product_name": "Indias Magic Masala Potato Chips", "confidence": 0.88},
        {"x1": 20, "y1": 450, "x2": 80, "y2": 550, "brand": "Lays", "product_name": "Tomato Tango Potato Chips", "confidence": 0.86, "pack_text": "Tomato Tango"},
        {"x1": 100, "y1": 455, "x2": 160, "y2": 545, "brand": "Lays", "product_name": "Tomato Tango Potato Chips", "confidence": 0.86, "pack_text": "Tomato"},
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx)
    assert stats["snack_row_recovery"] >= 2
    green_row = [r for r in updated if r["y1"] > 400]
    assert all(row["product_name"] == "American Style Cream and Onion Potato Chips" for row in green_row)


def test_snack_row_recovery_fixes_tomato_mislabel_on_blue_row():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((600, 400, 3), dtype=np.uint8)
    # Magic Masala blue row (BGR)
    source[350:450, 20:380, 0] = 110
    source[350:450, 20:380, 1] = 75
    source[350:450, 20:380, 2] = 90

    classified = [
        {
            "x1": 20,
            "y1": 350,
            "x2": 80,
            "y2": 450,
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "confidence": 0.88,
            "pack_text": "Tom",
        },
        {
            "x1": 100,
            "y1": 355,
            "x2": 160,
            "y2": 445,
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "confidence": 0.86,
            "pack_text": "Tomato",
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx, override_only=True)
    assert stats["snack_row_recovery"] >= 2
    assert all(row["product_name"] == "Indias Magic Masala Potato Chips" for row in updated)


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
    # top row Magic Masala teal (BGR → RGB R=100,G=90,B=140)
    source[50:150, 20:380, 0] = 140
    source[50:150, 20:380, 1] = 90
    source[50:150, 20:380, 2] = 100
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


def test_snack_row_override_fixes_cream_on_blue_bag():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((800, 400, 3), dtype=np.uint8)
    # Magic Masala blue-teal pixels (BGR)
    source[20:80, 20:380, 0] = 140
    source[20:80, 20:380, 1] = 90
    source[20:80, 20:380, 2] = 100

    classified = [
        {
            "x1": 20,
            "y1": 20,
            "x2": 80,
            "y2": 80,
            "brand": "Lays",
            "product_name": "American Style Cream and Onion Potato Chips",
            "confidence": 0.84,
            "pack_text": "Cream",
        },
        {
            "x1": 100,
            "y1": 25,
            "x2": 160,
            "y2": 75,
            "brand": "Lays",
            "product_name": "American Style Cream & Onion",
            "confidence": 0.82,
            "pack_text": "Cream &",
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx, override_only=True)
    assert stats["snack_row_recovery"] >= 2
    assert all(
        row["product_name"] == "Indias Magic Masala Potato Chips" for row in updated
    )


def test_snack_row_override_fixes_top_partial_color_mismatch():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((800, 400, 3), dtype=np.uint8)
    source[20:80, 20:380, 0] = 140
    source[20:80, 20:380, 1] = 90
    source[20:80, 20:380, 2] = 100

    classified = [
        {
            "x1": 20,
            "y1": 20,
            "x2": 80,
            "y2": 80,
            "brand": "Lays",
            "product_name": "American Style Cream and Onion Potato Chips",
            "confidence": 0.84,
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx, override_only=True)
    assert stats["snack_row_recovery"] == 1
    assert updated[0]["product_name"] == "Indias Magic Masala Potato Chips"


def test_snack_row_override_uses_row_color_when_edge_facing_unknown():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((600, 500, 3), dtype=np.uint8)
    for y in (100, 110):
        source[y : y + 90, 30:470, 0] = 140
        source[y : y + 90, 30:470, 1] = 90
        source[y : y + 90, 30:470, 2] = 100
    # left edge: green shelf strip bleed makes per-facing color unreliable
    source[100:190, 30:80, 1] = 160
    source[100:190, 30:80, 2] = 50

    classified = [
        {
            "x1": 30,
            "y1": 100,
            "x2": 80,
            "y2": 190,
            "brand": "Lays",
            "product_name": "American Style Cream and Onion Potato Chips",
            "confidence": 0.84,
            "pack_text": "Cream",
        },
        {
            "x1": 100,
            "y1": 105,
            "x2": 150,
            "y2": 185,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
        {
            "x1": 170,
            "y1": 108,
            "x2": 220,
            "y2": 182,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, source, ctx, override_only=True)
    assert stats["snack_row_recovery"] >= 1
    assert updated[0]["product_name"] == "Indias Magic Masala Potato Chips"


def test_finalize_fixes_green_tomato_mislabel():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((800, 400, 3), dtype=np.uint8)
    source[500:580, 20:380, 1] = 130
    source[500:580, 20:380, 2] = 100
    source[500:580, 20:380, 0] = 85

    classified = [
        {
            "x1": 20,
            "y1": 500,
            "x2": 80,
            "y2": 580,
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "confidence": 0.88,
            "pack_text": "Tomato",
        },
        {
            "x1": 100,
            "y1": 505,
            "x2": 160,
            "y2": 575,
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "confidence": 0.86,
            "pack_text": "Tom",
        },
    ]
    updated, fixed = finalize_lays_rack_labels(classified, source, ctx)
    assert fixed >= 2
    assert all(
        row["product_name"] == "American Style Cream and Onion Potato Chips" for row in updated
    )


def test_finalize_does_not_promote_top_partial_unknowns():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((900, 400, 3), dtype=np.uint8)
    source[120:200, 20:380, 0] = 140
    source[120:200, 20:380, 1] = 90
    source[120:200, 20:380, 2] = 100

    classified = [
        {
            "x1": 20,
            "y1": 20,
            "x2": 80,
            "y2": 80,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
        },
        {
            "x1": 100,
            "y1": 25,
            "x2": 160,
            "y2": 75,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
        },
        {
            "x1": 20,
            "y1": 120,
            "x2": 80,
            "y2": 200,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
        {
            "x1": 100,
            "y1": 125,
            "x2": 160,
            "y2": 195,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
    ]
    updated, fixed = finalize_lays_rack_labels(classified, source, ctx)
    assert fixed == 0
    top = [r for r in updated if r["y1"] < 100]
    assert all(r["brand"] == "Unknown" for r in top)


def test_top_partial_excluded_from_inventory():
    from app.inventory import aggregate_inventory
    from app.snack_row_recovery import mark_top_partial_exclusions

    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((900, 400, 3), dtype=np.uint8)
    classified = [
        {
            "x1": 20,
            "y1": 20,
            "x2": 80,
            "y2": 80,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
        {
            "x1": 20,
            "y1": 120,
            "x2": 80,
            "y2": 200,
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "confidence": 0.88,
        },
    ]
    updated, excluded = mark_top_partial_exclusions(classified, source, ctx)
    assert excluded == 1
    inventory = aggregate_inventory(updated)
    assert sum(row["quantity"] for row in inventory) == 1


def test_green_row_beats_tomato_mislabel_on_cream_row():
    ctx = resolve_scan_context({"category": "Packaged Food & Snacks · Chips"})
    source = np.zeros((800, 600, 3), dtype=np.uint8)
    source[400:500, 50:550, 1] = 160
    source[400:500, 50:550, 0] = 90
    source[400:500, 50:550, 2] = 60
    classified = [
        {
            "x1": 50,
            "y1": 400,
            "x2": 120,
            "y2": 500,
            "brand": "Lays",
            "product_name": "American Style Cream and Onion Potato Chips",
            "confidence": 0.88,
        },
        {
            "x1": 130,
            "y1": 405,
            "x2": 200,
            "y2": 495,
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "pack_text": "Tomato",
            "confidence": 0.86,
        },
    ]
    updated, fixed = finalize_lays_rack_labels(classified, source, ctx)
    assert fixed >= 1
    assert not any("tomato" in (r.get("product_name") or "").lower() for r in updated)

