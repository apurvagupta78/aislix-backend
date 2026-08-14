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


def test_recover_brand_for_ice_cream_sandwich_without_brand():
    from app.brand_dictionary import recover_label_from_context

    ctx = _ice_cream_context()
    partial = {
        "brand": "Unidentified SKU",
        "product_name": "Ice Cream Sandwich",
        "confidence": 0.99,
    }
    recovered = recover_label_from_context(partial, ctx, "")
    assert recovered is not None
    assert "amul" in recovered["brand"].lower()


def test_label_fits_rejects_snack_on_bread_context():
    from app.scan_context import label_fits_scan_context, resolve_scan_context

    ctx = resolve_scan_context(
        {
            "category": "Others",
            "sub_category": "others",
            "sub_category_custom": "Bread",
            "location": "Bread rack",
        }
    )
    snack_label = {
        "brand": "Jabsons",
        "product_name": "Roasted Peanuts",
        "sku": "jabsons_roasted_peanuts",
        "category": "Snacks",
    }
    assert label_fits_scan_context(snack_label, ctx) is False


def test_nacho_cheese_chips_not_foreign_dairy():
    from app.scan_context import foreign_aisle_conflict, resolve_scan_context

    ctx = resolve_scan_context(
        {"category": "Packaged Food & Snacks · Chips", "location": "A-2"}
    )
    conflict = foreign_aisle_conflict(
        "doritos nacho cheese",
        ctx,
        pack_text="nacho cheese flavoured",
    )
    assert conflict is None


def test_effective_sub_category_from_custom_bread():
    from app.scan_context import effective_sub_category, resolve_scan_context

    ctx = resolve_scan_context(
        {
            "category": "Others",
            "sub_category": "others",
            "sub_category_custom": "Bread",
        }
    )
    assert effective_sub_category(ctx) == "bread"


def test_kulfi_ocr_rejects_havmor_sandwich_label():
    from app.brand_dictionary import label_conflicts_with_pack_text

    label = {"brand": "Havmor", "product_name": "Sandwich Ice Cream", "sku": "havmor_sandwich_ice_cream_100_ml"}
    assert label_conflicts_with_pack_text(label, "Amul Rajbhog Kulfi") is True


def test_sandwich_ocr_rejects_amul_tricone_label():
    from app.brand_dictionary import label_conflicts_with_pack_text

    label = {"brand": "Amul", "product_name": "Tricone Vanilla Ice Cream", "sku": "amul_tricone_vanilla_ice_cream_40_ml"}
    assert label_conflicts_with_pack_text(label, "Amul Ice Cream Sandwich") is True


def test_funwith_ocr_maps_to_funwich():
    ctx = _ice_cream_context()
    result = match_from_text("Baskin Robbins Funwith Choco Vanilla", scan_context=ctx)
    assert result is not None
    assert "funwich" in (result.get("product_name") or "").lower()


def test_havmor_faiss_blocked_without_ocr_on_ice_cream_scan():
    ctx = _ice_cream_context()
    match = {
        "brand": "Havmor",
        "product_name": "Sandwich Ice Cream",
        "sku": "havmor_sandwich_ice_cream_100_ml",
        "category": "General",
    }
    assert _faiss_allowed_without_ocr(match, 0.95, ctx) is False


def test_funwith_inventory_alias_merges_with_funwich():
    from app.inventory import aggregate_inventory

    classified = [
        {"brand": "Baskin Robbins", "product_name": "Funwith", "confidence": 0.99, "category": "General"},
        {"brand": "Baskin Robbins", "product_name": "Funwich", "confidence": 0.99, "category": "General"},
    ]
    rows = aggregate_inventory(classified)
    assert len(rows) == 1
    assert rows[0]["product_name"] == "Funwich"
    assert rows[0]["quantity"] == 2
