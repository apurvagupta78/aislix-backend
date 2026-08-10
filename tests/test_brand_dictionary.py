"""Tests for OCR brand matching and variant-word disambiguation."""

from __future__ import annotations

from app.brand_dictionary import display_brand_name, match_brand_in_text, match_from_text


def test_head_and_shoulders_not_clean():
    text = "Head & Shoulders Classic Clean Shampoo 180ml"
    result = match_brand_in_text(text)
    assert result is not None
    brand, _conf = result
    assert brand == "Head"
    assert brand != "Clean"


def test_classic_clean_alone_can_still_match_clean_brand():
    text = "Classic Clean toothpaste"
    result = match_brand_in_text(text)
    # Without head/shoulders context, Clean may match if in catalog.
    assert result is not None


def test_himalaya_hint():
    text = "Himalaya Anti Hair Fall Shampoo 180ml"
    result = match_from_text(text)
    assert result is not None
    assert result["brand"].lower() == "himalaya"


def test_clinic_plus_hint():
    text = "Clinic Plus Strong and Long Health Shampoo"
    result = match_from_text(text)
    assert result is not None
    assert "clinic" in result["brand"].lower()


def test_display_head_and_shoulders():
    assert display_brand_name("Head", "And Shoulders Classic Clean Shampoo") == "Head & Shoulders"


def test_loreal_total_repair_hint():
    text = "L'Oreal Paris Total Repair 5 Shampoo 180ml"
    result = match_from_text(text)
    assert result is not None
    assert "loreal" in result["brand"].lower()
