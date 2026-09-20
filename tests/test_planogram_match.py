"""Tests for Astra CV ↔ planogram join quality."""

from app.planogram_match import _score_cv_to_planogram, join_planogram_with_cv


def test_brand_only_unverifiable_product_matches_odol():
    planogram = [
        {
            "brand": "Odol",
            "product_name": "Odol",
            "variant": "75g",
            "sku": "SKU-ODO-001",
            "sub_category": "Toothpaste",
            "expected_facings": 4,
            "expected_shelf_units": 4,
        }
    ]
    cv = [
        {
            "brand": "Odol",
            "brand_status": "IDENTIFIED",
            "product_name": "UNVERIFIABLE",
            "product_status": "UNVERIFIABLE",
            "variant": "UNVERIFIABLE",
            "variant_status": "UNVERIFIABLE",
            "actual_facings": 5,
            "actual_visible_units": 5,
            "confidence": 0.86,
        }
    ]
    rows = join_planogram_with_cv(planogram, cv)
    assert len(rows) == 1
    assert rows[0]["match_status"] == "BRAND_MATCHED"
    assert rows[0]["actual_facings"] == 5
    assert rows[0]["actual_visible_units"] == 5
    assert rows[0]["match_score"] >= 0.55


def test_colgate_brand_only_does_not_cross_match_doctor():
    planogram = [
        {
            "brand": "Doctor",
            "product_name": "Doctor Toothpaste",
            "variant": "100g",
            "sku": "SKU-DOC-001",
            "expected_facings": 5,
            "expected_shelf_units": 5,
        }
    ]
    cv = [
        {
            "brand": "Colgate",
            "brand_status": "IDENTIFIED",
            "product_name": "UNVERIFIABLE",
            "product_status": "UNVERIFIABLE",
            "actual_facings": 15,
            "actual_visible_units": 15,
        }
    ]
    rows = join_planogram_with_cv(planogram, cv)
    assert rows[0]["match_status"] in {"NOT_FOUND", "UNVERIFIABLE"}
    assert rows[0]["actual_facings"] is None


def test_full_identity_still_matched():
    planogram = [
        {
            "brand": "Colgate",
            "product_name": "MaxFresh",
            "variant": "150g",
            "sku": "SKU-COL-001",
            "expected_facings": 5,
        }
    ]
    cv = [
        {
            "brand": "Colgate",
            "brand_status": "IDENTIFIED",
            "product_name": "MaxFresh",
            "product_status": "IDENTIFIED",
            "variant": "150g",
            "variant_status": "IDENTIFIED",
            "actual_facings": 5,
            "actual_visible_units": 5,
        }
    ]
    rows = join_planogram_with_cv(planogram, cv)
    assert rows[0]["match_status"] == "MATCHED"
    assert rows[0]["actual_facings"] == 5


def test_placeholder_tokens_do_not_inflate_overlap():
    score = _score_cv_to_planogram(
        {
            "brand": "Colgate",
            "brand_status": "IDENTIFIED",
            "product_name": "UNVERIFIABLE",
            "product_status": "UNVERIFIABLE",
            "variant": "UNVERIFIABLE",
        },
        {"brand": "Colgate", "product_name": "MaxFresh", "variant": "150g"},
    )
    assert score >= 0.55
