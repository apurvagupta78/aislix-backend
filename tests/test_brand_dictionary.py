"""Tests for OCR brand matching and variant-word disambiguation."""

from __future__ import annotations

from app.brand_dictionary import display_brand_name, label_conflicts_with_pack_text, match_brand_in_text, match_from_text


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


def test_pears_not_blue_bird():
    text = "Pears Pure and Gentle Soap 125g"
    result = match_from_text(text)
    assert result is not None
    assert result["brand"].lower() == "pears"
    assert "blue" not in result["brand"].lower()


def test_smooth_shine_blue_not_blue_bird():
    text = "Smooth and Shine blue bottle"
    result = match_from_text(text)
    if result:
        assert result["brand"].lower() != "blue"


def test_dettol_handwash():
    text = "Dettol Original Hand Wash 200ml"
    result = match_from_text(text)
    assert result is not None
    assert result["brand"].lower() == "dettol"
    assert "hand" in (result.get("product_name") or "").lower()


def test_keratin_smooth_tresemme():
    text = "Keratin Smooth Shampoo 185ml Tresemme"
    result = match_from_text(text)
    assert result is not None
    assert "tresemme" in result["brand"].lower()
    assert "keratin" in (result.get("product_name") or "").lower()


def test_taj_blocked_on_shampoo_pack():
    text = "Dove Intense Repair Shampoo Taj Mahal tea"
    result = match_from_text(text)
    assert result is not None
    assert result["brand"].lower() == "dove"


def test_pantene_conflicts_with_head_shoulders_ocr():
    label = {"brand": "Pantene", "product_name": "Lively Clean Shampoo"}
    text = "Head & Shoulders Classic Clean 180ml"
    assert label_conflicts_with_pack_text(label, text) is True
