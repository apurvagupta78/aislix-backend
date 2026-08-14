"""Tests for Phase 2C category-scoped learned SKU search."""

from __future__ import annotations

from app.category_scope import (
    effective_entry_ids,
    enrich_learned_entry,
    entry_matches_scope,
    filter_scoped_candidates,
)


def _tea_context() -> dict:
    return {
        "aislix_category": "Beverages",
        "aislix_category_id": "beverages",
        "sub_category": "tea",
        "sub_category_label": "Tea",
    }


def _shampoo_context() -> dict:
    return {
        "aislix_category": "Personal Care",
        "aislix_category_id": "personal_care",
        "sub_category": "shampoo",
        "sub_category_label": "Shampoo",
    }


def test_effective_entry_ids_from_category_label():
    entry = {"brand": "TajMahal", "category": "Beverages · Tea"}
    enrich_learned_entry(entry)
    assert entry["category_id"] == "beverages"
    assert entry["sub_category_id"] == "tea"


def test_effective_entry_ids_from_brand_when_others():
    entry = {"brand": "Tresemme", "category": "Others · Others"}
    cat_id, sub_id = effective_entry_ids(entry)
    assert cat_id == "personal_care"
    assert sub_id == "shampoo"


def test_entry_matches_scope_rejects_cross_category():
    snack = {
        "brand": "The Whole Truth",
        "product_name": "Protein Bar",
        "category_id": "packaged_food_snacks",
        "sub_category_id": "chips",
    }
    assert not entry_matches_scope(snack, _tea_context())
    assert entry_matches_scope(snack, _shampoo_context()) is False


def test_entry_matches_scope_accepts_tea_brand_on_tea_scan():
    tea = {
        "brand": "Tetley",
        "product_name": "Green Tea",
        "category_id": "beverages",
        "sub_category_id": "tea",
    }
    assert entry_matches_scope(tea, _tea_context())


def test_filter_scoped_candidates_prefers_in_scope_match():
    catalog = [
        {"brand": "Twinings", "category_id": "beverages", "sub_category_id": "tea"},
        {"brand": "The Whole Truth", "category_id": "packaged_food_snacks", "sub_category_id": "chips"},
        {"brand": "Tetley", "category_id": "beverages", "sub_category_id": "tea"},
    ]
    ids = [1, 0, 2]
    scores = [0.99, 0.98, 0.95]
    entry, score = filter_scoped_candidates(
        catalog, ids, scores, _tea_context(), strict_sub=True, threshold=0.9
    )
    assert entry is not None
    assert entry["brand"] in {"Twinings", "Tetley"}
    assert entry["brand"] != "The Whole Truth"
    assert score >= 0.9


def test_filter_scoped_candidates_returns_none_when_only_cross_category():
    catalog = [
        {"brand": "Nivea", "category_id": "personal_care", "sub_category_id": "skincare"},
    ]
    entry, score = filter_scoped_candidates(
        catalog, [0], [0.99], _tea_context(), strict_sub=True, threshold=0.85
    )
    assert entry is None
