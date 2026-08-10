"""Tests for cross-aisle SKU guards."""

from __future__ import annotations

from app.scan_context import sku_allowed_in_context


def _ctx(aisle: str, hints: set[str] | None = None) -> dict:
    from app.scan_context import AISLIX_TO_CATALOG, resolve_aislix_category

    resolved = resolve_aislix_category(aisle)
    key = (resolved or {}).get("name") or aisle
    catalog = AISLIX_TO_CATALOG.get(key.lower(), ["general"])
    return {
        "aislix_category": aisle,
        "catalog_categories": catalog,
        "brand_hints": hints or set(),
    }


def test_rite_bite_blocked_on_personal_care():
    assert sku_allowed_in_context(
        "Rite",
        sku="rite_bite_max_protein_ultimate_choco_berry",
        entry_category="Snacks",
        context=_ctx("Personal Care"),
    ) is False


def test_rite_bite_allowed_on_snacks_aisle():
    assert sku_allowed_in_context(
        "Rite",
        sku="rite_bite_max_protein_ultimate_choco_berry",
        entry_category="Snacks",
        context=_ctx("Packaged Food & Snacks", {"rite", "britannia"}),
    ) is True


def test_coca_blocked_on_personal_care():
    assert sku_allowed_in_context(
        "Coca",
        sku="coca_cola_600ml",
        entry_category="Beverages",
        context=_ctx("Personal Care"),
    ) is False


def test_coca_allowed_on_beverages_aisle():
    assert sku_allowed_in_context(
        "Coca",
        sku="coca_cola_600ml",
        entry_category="Beverages",
        context=_ctx("Beverages", {"coca cola", "pepsi"}),
    ) is True


def test_lipton_allowed_on_beverages():
    assert sku_allowed_in_context(
        "Lipton",
        sku="lipton_green_tea",
        entry_category="Beverages",
        context=_ctx("Beverages", {"lipton", "tetley"}),
    ) is True


def test_shampoo_sku_blocked_on_beverages():
    assert sku_allowed_in_context(
        "Dove",
        sku="dove_intense_repair_shampoo_180ml",
        entry_category="Personal Care",
        context=_ctx("Beverages"),
    ) is False


def test_blue_bird_allowed_on_grocery():
    assert sku_allowed_in_context(
        "Blue",
        sku="blue_bird_caster_sugar",
        entry_category="Staples",
        context=_ctx("Grocery & Staples", {"blue bird"}),
    ) is True


def test_blue_blocked_on_beverages():
    assert sku_allowed_in_context(
        "Blue",
        sku="blue_bird_caster_sugar",
        entry_category="Staples",
        context=_ctx("Beverages"),
    ) is False


def test_sunsilk_protein_shampoo_allowed_on_personal_care():
    assert sku_allowed_in_context(
        "Sunsilk",
        sku="sunsilk_nourishing_soft_smooth_shampoo_with_egg_protein_almond_oil_vitamin_c_for_2x_smoother_softer_hair_180_ml_180_ml",
        entry_category="Personal Care",
        context=_ctx("Personal Care", {"sunsilk", "dove"}),
    ) is True


def test_taj_blocked_on_personal_care():
    assert sku_allowed_in_context(
        "Taj",
        sku="taj_mahal_tea",
        entry_category="Beverages",
        context=_ctx("Personal Care", {"dove", "pantene"}),
    ) is False
