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
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    assert len(rows) == 1
    assert len(unplanned) == 0
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
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    assert rows[0]["match_status"] in {"NOT_FOUND", "UNVERIFIABLE"}
    assert rows[0]["actual_facings"] is None
    assert len(unplanned) == 1
    assert unplanned[0]["actual_facings"] == 15


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
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    assert rows[0]["match_status"] == "MATCHED"
    assert rows[0]["actual_facings"] == 5
    assert unplanned == []


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


def test_lays_variant_unverifiable_attaches_to_remaining_planogram_row():
    """Scan 2917f430 class: blue packs with illegible flavor → STT row gets Astra counts."""
    planogram = [
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Magic Masala",
            "sku": "lays-mm",
            "sub_category": "chips",
            "expected_facings": 19,
            "expected_shelf_units": 19,
        },
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Spanish Tomato Tango",
            "sku": "lays-tt",
            "sub_category": "chips",
            "expected_facings": 6,
            "expected_shelf_units": 6,
        },
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Cream & Onion",
            "sku": "lays-co",
            "sub_category": "chips",
            "expected_facings": 12,
            "expected_shelf_units": 12,
        },
    ]
    cv = [
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "Magic Masala",
            "variant_status": "IDENTIFIED",
            "actual_facings": 19,
            "actual_visible_units": 13,
            "confidence": 0.86,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "UNVERIFIABLE",
            "variant_status": "UNVERIFIABLE",
            "actual_facings": 6,
            "actual_visible_units": 6,
            "confidence": 0.83,
            "visual_notes": "Six distinct blue-package fronts; variant text not legible.",
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "Cream & Onion",
            "variant_status": "IDENTIFIED",
            "actual_facings": 12,
            "actual_visible_units": 6,
            "confidence": 0.8,
        },
    ]
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    assert len(unplanned) == 0
    by_variant = {str(r["variant"]): r for r in rows}
    assert by_variant["Magic Masala"]["match_status"] == "MATCHED"
    assert by_variant["Magic Masala"]["actual_facings"] == 19
    assert by_variant["Cream & Onion"]["match_status"] == "MATCHED"
    assert by_variant["Cream & Onion"]["actual_facings"] == 12
    stt = by_variant["Spanish Tomato Tango"]
    assert stt["actual_facings"] == 6
    assert stt["actual_visible_units"] == 6
    assert stt["source_actual"] == "astra"
    assert stt["match_status"] == "BRAND_MATCHED"
    assert stt["variant_status"] == "UNVERIFIABLE"


def test_two_unverifiable_variants_do_not_guess_which_flavor():
    planogram = [
        {
            "brand": "Lay's",
            "product_name": "Potato chips",
            "variant": "Spanish Tomato Tango",
            "expected_facings": 6,
        },
        {
            "brand": "Lay's",
            "product_name": "Potato chips",
            "variant": "Classic Salted",
            "expected_facings": 6,
        },
    ]
    cv = [
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "UNVERIFIABLE",
            "variant_status": "UNVERIFIABLE",
            "actual_facings": 6,
            "actual_visible_units": 6,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "UNVERIFIABLE",
            "variant_status": "UNVERIFIABLE",
            "actual_facings": 5,
            "actual_visible_units": 5,
        },
    ]
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    # Ambiguous: leave both planogram rows open and both CV rows unplanned.
    assert all(r.get("source_actual") is None for r in rows)
    assert all(r["actual_facings"] is None for r in rows)
    assert len(unplanned) == 2


def test_tangy_tomato_matches_spanish_tomato_tango_planogram():
    """Astra OCR alternate flavor name must attach to planogram STT SKU."""
    planogram = [
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Magic Masala",
            "sku": "lays-mm",
            "expected_facings": 19,
            "expected_shelf_units": 19,
        },
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Spanish Tomato Tango",
            "sku": "lays-tt",
            "expected_facings": 6,
            "expected_shelf_units": 6,
        },
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Cream & Onion",
            "sku": "lays-co",
            "expected_facings": 12,
            "expected_shelf_units": 12,
        },
    ]
    cv = [
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product": "Lay's Magic Masala Potato Chips",
            "variant": "Magic Masala",
            "actual_facings": 19,
            "actual_visible_units": 19,
            "confidence": 0.9,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product": "Lay's Tangy Tomato Potato Chips",
            "variant": "Tangy Tomato",
            "actual_facings": 6,
            "actual_visible_units": 7,
            "confidence": 0.64,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product": "Lay's Cream & Onion Potato Chips",
            "variant": "Cream & Onion",
            "actual_facings": 12,
            "actual_visible_units": 12,
            "confidence": 0.8,
        },
    ]
    rows, unplanned = join_planogram_with_cv(planogram, cv)
    assert unplanned == []
    by_sku = {str(r["sku"]): r for r in rows}
    assert by_sku["lays-mm"]["match_status"] == "MATCHED"
    assert by_sku["lays-mm"]["actual_facings"] == 19
    stt = by_sku["lays-tt"]
    assert stt["match_status"] == "MATCHED"
    assert stt["actual_facings"] == 6
    assert stt["actual_visible_units"] == 7
    assert stt["source_actual"] == "astra"
    assert by_sku["lays-co"]["match_status"] == "MATCHED"
    assert by_sku["lays-co"]["actual_facings"] == 12
