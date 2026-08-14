"""Tests for sub-category compliance / category mismatch detection."""

from __future__ import annotations

import pytest

from app.scan_context import COMPLIANCE_ALERT_INTERPRETATION, COMPLIANCE_ALERT_TITLE
from app.subcategory_compliance import analyze_subcategory_compliance, infer_detected_subcategory


def _facing(brand: str, product: str, **extra) -> dict:
    return {
        "brand": brand,
        "product_name": product,
        "variant": "",
        "confidence": 0.92,
        "category": "General",
        "x1": 10,
        "y1": 10,
        "x2": 50,
        "y2": 50,
        **extra,
    }


def _soap_context() -> dict:
    return {
        "aislix_category": "Personal Care",
        "sub_category": "soap",
        "sub_category_label": "Soap",
        "catalog_categories": ["personal care"],
        "brand_hints": {
            "dove", "lux", "dettol", "colgate", "tresemme", "indulekha", "himalaya",
        },
    }


def test_dettol_soap_is_compliant_on_soap_audit():
    item = _facing("Dettol", "Original Soap")
    detected = infer_detected_subcategory(item, _soap_context())
    assert detected == "soap"


def test_tresemme_shampoo_mismatch_on_soap_audit():
    classified = [_facing("Tresemme", "Keratin Smooth Shampoo")]
    result = analyze_subcategory_compliance(classified, _soap_context())
    assert result["misplaced_facings"] == 1
    assert classified[0]["subcategory_match"] is False
    assert classified[0]["detected_sub_category"] == "shampoo"


def test_dove_soap_not_mismatch():
    classified = [_facing("Dove", "Beauty Soap Bar")]
    result = analyze_subcategory_compliance(classified, _soap_context())
    assert result["misplaced_facings"] == 0
    assert classified[0]["subcategory_match"] is True


def test_dove_shampoo_is_mismatch_on_soap_audit():
    classified = [_facing("Dove", "Intense Repair Shampoo")]
    result = analyze_subcategory_compliance(classified, _soap_context())
    assert result["misplaced_facings"] == 1


def test_no_subcategory_skips_compliance():
    classified = [_facing("Tresemme", "Keratin Smooth Shampoo")]
    result = analyze_subcategory_compliance(classified, {"aislix_category": "Personal Care"})
    assert result["misplaced_facings"] == 0
    assert result["compliance_alerts"] == []


def test_compliance_alert_uses_standard_messaging():
    classified = [_facing("Colgate", "MaxFresh Toothpaste")]
    result = analyze_subcategory_compliance(classified, _soap_context())
    assert len(result["compliance_alerts"]) == 1
    alert = result["compliance_alerts"][0]
    assert alert["title"] == COMPLIANCE_ALERT_TITLE
    assert alert["interpretation"] == COMPLIANCE_ALERT_INTERPRETATION


def test_tea_audit_flags_cola():
    ctx = {
        "aislix_category": "Beverages",
        "sub_category": "tea",
        "sub_category_label": "Tea",
        "catalog_categories": ["beverages"],
        "brand_hints": set(),
    }
    classified = [_facing("Coca", "Coke")]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 1


def test_pizza_sauce_mismatch_on_soap_audit():
    classified = [_facing("Ragu", "Homemade Style Pizza Sauce")]
    result = analyze_subcategory_compliance(classified, _soap_context())
    assert result["misplaced_facings"] == 1
    assert classified[0]["detected_sub_category_label"] == "Packaged Food & Snacks"


def test_loreal_staples_category_not_mismatch_on_shampoo_audit():
    """PC brand with wrong catalog Staples tag should not trigger compliance alert."""
    ctx = {
        "aislix_category": "Personal Care",
        "sub_category": "shampoo",
        "sub_category_label": "Shampoo",
        "catalog_categories": ["personal care"],
        "brand_hints": {
            "dove", "pantene", "sunsilk", "loreal", "l'oreal", "tresemme", "himalaya",
        },
    }
    classified = [_facing("Loreal", "Paris 6 Oil Nourish Conditioner 180Ml", category="Staples")]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 0
    assert classified[0]["subcategory_match"] is True


def test_sunsilk_egg_protein_shampoo_not_cross_aisle_mismatch():
    """Shampoo SKUs containing 'protein' must not trigger snack cross-aisle guard."""
    ctx = {
        "aislix_category": "Personal Care",
        "sub_category": "shampoo",
        "sub_category_label": "Shampoo",
        "catalog_categories": ["personal care"],
        "brand_hints": {"sunsilk", "dove", "pantene"},
    }
    classified = [
        _facing(
            "Sunsilk",
            "Nourishing Soft Smooth Shampoo With Egg Protein Almond Oil Vitamin C 180 Ml",
            sku="sunsilk_nourishing_soft_smooth_shampoo_with_egg_protein_almond_oil_vitamin_c_for_2x_smoother_softer_hair_180_ml_180_ml",
            category="Personal Care",
        )
    ]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 0
    assert classified[0]["subcategory_match"] is True


def test_taj_blocked_on_shampoo_audit():
    from app.scan_context import sub_category_blocks_brand

    ctx = {
        "aislix_category": "Personal Care",
        "sub_category": "shampoo",
        "brand_hints": {"dove", "pantene", "sunsilk"},
    }
    assert sub_category_blocks_brand(ctx, "Taj", "", product_name="Mahal") is True


def test_nivea_roll_on_blocked_on_shampoo_audit():
    from app.scan_context import sub_category_blocks_brand

    ctx = {
        "aislix_category": "Personal Care",
        "sub_category": "shampoo",
        "brand_hints": {"dove", "pantene", "sunsilk", "head & shoulders"},
    }
    assert sub_category_blocks_brand(
        ctx, "Nivea", "", product_name="Pearl Beauty Roll On"
    ) is True


def test_doritos_nacho_cheese_compliant_on_chips_audit():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "sub_category_label": "Chips",
        "catalog_categories": ["snacks", "bakery & biscuits"],
        "brand_hints": {"lays", "kurkure", "bingo", "haldiram"},
    }
    classified = [_facing("Doritos", "Nacho Cheese", pack_text="nacho cheese")]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 0


def test_kurkure_masala_munch_compliant_on_chips_audit():
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "sub_category_label": "Chips",
        "catalog_categories": ["snacks", "bakery & biscuits"],
        "brand_hints": {"lays", "kurkure", "bingo"},
    }
    classified = [_facing("Kurkure", "Masala Munch", pack_text="masala munch")]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 0


