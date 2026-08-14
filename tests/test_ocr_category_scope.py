"""Tests for cross-aisle OCR, category scope, and ice-cream recognition fixes."""

from __future__ import annotations

from app.brand_dictionary import match_from_text
from app.category_scope import effective_entry_ids
from app.recognizer import _accept_faiss_fusion, _faiss_allowed_without_ocr
from app.scan_context import aisle_brand_override_allowed, resolve_scan_context, sku_allowed_in_context
from app.sku_category_map import map_class_to_aislix_category
from app.subcategory_compliance import _subcategory_product_guard


def _ice_cream_context() -> dict:
    return resolve_scan_context(
        {
            "category": "Frozen Foods & Ice Cream · Ice cream",
            "location": "A-1-D",
        }
    )


def test_kulfi_sku_maps_to_frozen_not_dairy():
    mapped = map_class_to_aislix_category("amul_rabdi_kulfi_ice_cream_stick_36_gms")
    assert mapped["category_id"] == "frozen_ice_cream"
    assert mapped["sub_category_id"] == "ice_cream"


def test_amul_milk_still_maps_to_dairy():
    mapped = map_class_to_aislix_category("amul_toned_milk_500_ml")
    assert mapped["category_id"] == "dairy_chilled"


def test_amul_kulfi_allowed_on_ice_cream_scan():
    ctx = _ice_cream_context()
    allowed = sku_allowed_in_context(
        "Amul",
        sku="amul_rabdi_kulfi_ice_cream_stick_36_gms",
        entry_category="General",
        context=ctx,
    )
    assert allowed is True


def test_amul_kulfi_ocr_hint():
    ctx = _ice_cream_context()
    result = match_from_text("Amul Rabdi Kulfi ice cream stick", scan_context=ctx)
    assert result is not None
    assert "amul" in result["brand"].lower()
    assert "kulfi" in (result.get("product_name") or "").lower()


def test_amul_brand_only_on_ice_cream_scan_prefers_kulfi_sku():
    ctx = _ice_cream_context()
    result = match_from_text("Amul", scan_context=ctx)
    assert result is not None
    assert "amul" in result["brand"].lower()
    sku = (result.get("sku") or "").lower()
    product = (result.get("product_name") or "").lower()
    assert "kulfi" in sku or "ice cream" in product or "kulfi" in product


def test_brooklyn_aisle_brand_override():
    ctx = _ice_cream_context()
    assert aisle_brand_override_allowed("Brooklyn", "Ice Cream", context=ctx) is True


def test_brooklyn_ice_cream_compliance_guard():
    assert _subcategory_product_guard("ice_cream", "brooklyn ice cream", "") is True


def test_faiss_without_ocr_allowed_when_scoped():
    ctx = _ice_cream_context()
    match = {
        "brand": "Amul",
        "product_name": "Rabdi Kulfi Ice Cream Stick",
        "sku": "amul_rabdi_kulfi_ice_cream_stick_36_gms",
        "category": "General",
    }
    assert _faiss_allowed_without_ocr(match, 0.93, ctx) is True


def test_faiss_fusion_accepts_scoped_match_without_ocr():
    ctx = _ice_cream_context()
    match = {
        "brand": "Amul",
        "product_name": "Rabdi Kulfi Ice Cream Stick",
        "sku": "amul_rabdi_kulfi_ice_cream_stick_36_gms",
        "category": "General",
    }
    assert _accept_faiss_fusion(match, 0.93, "", None, ctx) is True


def test_effective_entry_ids_kulfi_sku_is_frozen():
    cat_id, sub_id = effective_entry_ids(
        {
            "brand": "Amul",
            "product_name": "Rabdi Kulfi Ice Cream Stick",
            "sku": "amul_rabdi_kulfi_ice_cream_stick_36_gms",
            "category": "General",
        }
    )
    assert cat_id == "frozen_ice_cream"
    assert sub_id == "ice_cream"


def test_aisle_category_matches_learned_full_label():
    from app.scan_context import aisle_category_matches

    assert aisle_category_matches(
        "Frozen Foods & Ice Cream · Ice cream",
        "Frozen Foods & Ice Cream",
    )


def test_brooklyn_learned_category_not_compliance_mismatch():
    from app.subcategory_compliance import analyze_subcategory_compliance

    ctx = {
        "aislix_category": "Frozen Foods & Ice Cream",
        "aislix_category_id": "frozen_ice_cream",
        "sub_category": "ice_cream",
        "sub_category_label": "Ice cream",
        "catalog_categories": ["dairy", "general", "snacks"],
        "brand_hints": {"amul", "baskin robbins", "brooklyn"},
    }
    classified = [{
        "brand": "Brooklyn",
        "product_name": "Ice Cream",
        "category": "Frozen Foods & Ice Cream · Ice cream",
        "confidence": 0.9,
        "x1": 0, "y1": 0, "x2": 10, "y2": 10,
    }]
    out = analyze_subcategory_compliance(classified, ctx)
    assert out["misplaced_facings"] == 0
