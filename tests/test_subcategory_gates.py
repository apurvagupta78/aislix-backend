"""Tests for go-live sub-category guards and FAISS acceptance gates."""

from __future__ import annotations

from app.brand_dictionary import label_conflicts_with_pack_text
from app.recognizer import _accept_faiss_fusion
from app.scan_context import product_type_matches_sub_category, sub_category_blocks_brand


def test_hersheys_blocked_on_chips_subcategory():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "brand_hints": {"lays", "bingo", "crax", "kurkure"},
    }
    assert sub_category_blocks_brand(
        ctx,
        "Hersheys",
        "",
        product_name="Kisses Hazelnut N Cookies Milk Chocolate",
    ) is True


def test_bagrrys_blocked_on_chips_subcategory():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "brand_hints": {"lays", "bingo", "crax"},
    }
    assert sub_category_blocks_brand(
        ctx,
        "Bagrrys",
        "",
        product_name="Crunchy Muesli Almond Raisins And Honey",
    ) is True


def test_lays_allowed_on_chips_subcategory():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "brand_hints": {"lays", "bingo", "crax", "kurkure"},
    }
    assert sub_category_blocks_brand(
        ctx,
        "Lays",
        "lays potato chips classic",
        product_name="Potato Chips",
    ) is False


def test_product_type_rejects_chocolate_on_chips_audit():
    label = {
        "brand": "Hersheys",
        "product_name": "Kisses Hazelnut N Cookies Milk Chocolate",
        "sku": "hersheys_kisses_hazelnut_n_cookies_milk_chocolate_33_gms",
    }
    assert product_type_matches_sub_category("chips", label, "") is False


def test_product_type_allows_tea_on_tea_audit():
    label = {
        "brand": "Tata",
        "product_name": "Tea Agni",
        "sku": "tata_tea_agni",
    }
    assert product_type_matches_sub_category("tea", label, "tata tea agni") is True


def test_ocr_conflict_bingo_vs_hersheys():
    label = {
        "brand": "Hersheys",
        "product_name": "Kisses Hazelnut N Cookies Milk Chocolate",
    }
    assert label_conflicts_with_pack_text(label, "bingo tedhe medhe masala tadka") is True


def test_faiss_rejects_phantom_on_chips_with_strict_gate():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "catalog_categories": ["snacks", "bakery & biscuits"],
        "brand_hints": {"lays", "bingo", "crax", "kurkure", "pringles"},
    }
    match = {
        "brand": "Hersheys",
        "product_name": "Kisses Hazelnut N Cookies Milk Chocolate",
        "sku": "hersheys_kisses_hazelnut_n_cookies_milk_chocolate_33_gms",
        "category": "Bakery & Biscuits",
    }
    assert _accept_faiss_fusion(
        match,
        0.99,
        "bingo tedhe medhe",
        "Packaged Food & Snacks",
        scan_context=ctx,
    ) is False


def test_faiss_accepts_tea_on_tea_audit_with_weak_ocr():
    ctx = {
        "aislix_category": "Beverages",
        "sub_category": "tea",
        "catalog_categories": ["beverages"],
        "brand_hints": {"tata", "lipton", "tetley", "taj mahal"},
    }
    match = {
        "brand": "Tata",
        "product_name": "Tea Agni",
        "sku": "tata_tea_agni",
        "category": "Beverages",
    }
    assert _accept_faiss_fusion(
        match,
        0.96,
        "premium blend tea leaves",
        "Beverages",
        scan_context=ctx,
    ) is True
