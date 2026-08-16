"""Regression: mixed snack racks must not collapse to Lay's Tomato Tango."""

from __future__ import annotations

import numpy as np

from app.brand_dictionary import label_conflicts_with_pack_text, match_from_text
from app.scan_context import resolve_scan_context
from app.snack_row_recovery import recover_snack_variants_by_row


def test_flavor_hints_require_lays_brand_in_ocr():
    ctx = {"sub_category": "chips"}
    assert match_from_text("magic masala potato chips", scan_context=ctx) is None
    assert match_from_text("tomato tango potato chips", scan_context=ctx) is None
    match = match_from_text("lays magic masala potato chips", scan_context=ctx)
    assert match is not None
    assert (match.get("brand") or "").lower().startswith("lay")


def test_label_conflict_lays_vs_kurkure_pack_text():
    label = {"brand": "Lays", "product_name": "Tomato Tango Potato Chips"}
    assert label_conflicts_with_pack_text(label, "Kurkure Masala Munch")
    assert label_conflicts_with_pack_text(label, "Bingo Tedhe Medhe")
    assert not label_conflicts_with_pack_text(label, "Lays Tomato Tango")


def test_mixed_snack_row_does_not_force_tomato_tango():
    ctx = resolve_scan_context(
        {"category": "Packaged Food & Snacks", "sub_category": "chips"}
    )
    source = np.zeros((600, 500, 3), dtype=np.uint8)
    # Warm orange/red snack-bag pixels (Kurkure/Bingo-like).
    source[100:200, 30:470, 0] = 50
    source[100:200, 30:470, 1] = 80
    source[100:200, 30:470, 2] = 200

    classified = [
        {
            "x1": 30,
            "y1": 100,
            "x2": 90,
            "y2": 200,
            "brand": "Kurkure",
            "product_name": "Masala Munch",
            "confidence": 0.88,
            "pack_text": "Kurkure Masala Munch",
        },
        {
            "x1": 100,
            "y1": 105,
            "x2": 160,
            "y2": 195,
            "brand": "Kurkure",
            "product_name": "Masala Munch",
            "confidence": 0.86,
            "pack_text": "kurkure",
        },
        {
            "x1": 170,
            "y1": 110,
            "x2": 230,
            "y2": 190,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
        },
        {
            "x1": 240,
            "y1": 350,
            "x2": 300,
            "y2": 450,
            "brand": "Bingo",
            "product_name": "Tedhe Medhe",
            "confidence": 0.87,
            "pack_text": "Bingo Tedhe Medhe",
        },
        {
            "x1": 310,
            "y1": 355,
            "x2": 370,
            "y2": 445,
            "brand": "Bingo",
            "product_name": "Tedhe Medhe",
            "confidence": 0.85,
            "pack_text": "bingo",
        },
    ]

    updated, stats = recover_snack_variants_by_row(classified, source, ctx)

    kurkure = [r for r in updated if (r.get("brand") or "").lower() == "kurkure"]
    bingo = [r for r in updated if (r.get("brand") or "").lower() == "bingo"]
    assert len(kurkure) == 3
    assert all(r["product_name"] == "Masala Munch" for r in kurkure)
    assert len(bingo) == 2
    assert all(r["product_name"] == "Tedhe Medhe" for r in bingo)

    tomato = [
        r
        for r in updated
        if r.get("product_name") == "Tomato Tango Potato Chips"
    ]
    assert tomato == []

    unknown = [r for r in updated if r.get("brand") == "Unknown"]
    assert len(unknown) == 0
    assert stats["snack_row_recovery"] >= 1


def test_partial_fragment_resolves_short_lays_ocr():
    ctx = {"sub_category": "chips"}
    match = match_from_text("magic masala", scan_context=ctx)
    assert match is not None
    assert "magic masala" in (match.get("product_name") or "").lower()

    match = match_from_text("magic", scan_context=ctx)
    assert match is not None
    assert (match.get("brand") or "").lower().startswith("lay")

    assert match_from_text("rings", scan_context=ctx) is not None
    assert (match_from_text("rings", scan_context=ctx) or {}).get("brand") == "Crax"


def test_personal_care_blocks_food_skus():
    from app.brand_dictionary import personal_care_food_mismatch

    ctx = {"aislix_category": "Personal Care", "sub_category": "shampoo"}
    label = {"brand": "Dabur", "product_name": "Hajmola Imli Digestive Tablets"}
    assert personal_care_food_mismatch(label, ctx)
    assert not personal_care_food_mismatch({"brand": "Dove", "product_name": "Shampoo"}, ctx)


def test_lays_flavor_scoring_picks_correct_sku():
    from app.brand_dictionary import match_product_for_brand

    ctx = {"sub_category": "chips"}
    match = match_product_for_brand("Lays", "lays magic masala potato chips", scan_context=ctx)
    assert match is not None
    assert "magic masala" in (match.get("product_name") or "").lower()


def test_vatika_ocr_does_not_resolve_to_hajmola():
    ctx = {"aislix_category": "Personal Care", "sub_category": "shampoo"}
    match = match_from_text("dabur vatika naturals health shine shampoo", scan_context=ctx)
    assert match is not None
    assert "hajmola" not in (match.get("product_name") or "").lower()
    assert "vatika" in (match.get("product_name") or "").lower()


def test_lays_ocr_conflicts_with_bingo_label():
    from app.brand_dictionary import label_conflicts_with_pack_text

    label = {"brand": "Bingo", "product_name": "Mad Angles Chips Pizza Aah"}
    assert label_conflicts_with_pack_text(label, "Lays Classic Salted Potato Chips")


def test_ambiguous_tango_fragment_not_mapped_without_lays():
    ctx = {"sub_category": "chips"}
    assert match_from_text("tango", scan_context=ctx) is None
    assert match_from_text("tomato", scan_context=ctx) is None
    assert match_from_text("tomato tango potato chips", scan_context=ctx) is None
    match = match_from_text("lays tomato tango", scan_context=ctx)
    assert match is not None
    assert "tomato tango" in (match.get("product_name") or "").lower()


def test_nivea_men_shampoo_not_lotion_on_shampoo_scan():
    from app.brand_dictionary import match_product_for_brand

    ctx = {"aislix_category": "Personal Care", "sub_category": "shampoo"}
    match = match_from_text("nivea men strong power shampoo", scan_context=ctx)
    assert match is not None
    assert "shampoo" in (match.get("product_name") or "").lower()
    assert "lotion" not in (match.get("product_name") or "").lower()

    bare = match_product_for_brand("Nivea", "nivea", scan_context=ctx)
    assert bare is not None
    assert "lotion" not in (bare.get("product_name") or "").lower()


def test_ambiguous_cream_fragment_not_mapped_to_cream_onion():
    ctx = {"sub_category": "chips"}
    assert match_from_text("cream", scan_context=ctx) is None
    assert match_from_text("crear", scan_context=ctx) is None
    match = match_from_text("cream onion", scan_context=ctx)
    assert match is not None
    assert "cream" in (match.get("product_name") or "").lower()


def test_mixed_snack_row_recovers_unknown_from_neighbor():
    ctx = {"aislix_category": "Packaged Food & Snacks", "sub_category": "biscuits"}
    classified = [
        {
            "x1": 30,
            "y1": 100,
            "x2": 90,
            "y2": 200,
            "brand": "Crax",
            "product_name": "Curls",
            "confidence": 0.9,
            "pack_text": "Crax Curls",
        },
        {
            "x1": 100,
            "y1": 105,
            "x2": 160,
            "y2": 195,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "pack_text": "crax curls",
        },
    ]
    updated, stats = recover_snack_variants_by_row(classified, np.zeros((400, 300, 3), dtype=np.uint8), ctx)
    assert stats["snack_row_recovery"] >= 1
    unknown = [r for r in updated if r.get("brand") == "Unknown"]
    assert len(unknown) == 0
