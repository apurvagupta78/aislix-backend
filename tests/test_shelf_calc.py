from app.shelf_calc import (
    build_planogram_analysis,
    build_planogram_row_metrics,
    build_shelf_only_analysis,
    calculate_facing_compliance,
    calculate_facing_compliance_aggregate,
    calculate_visible_shelf_coverage_days,
    calculate_visible_unit_shortfall,
    calculate_visible_unit_value_gap,
    normalize_brand,
    normalize_product_identity,
)


def test_normalize_brand_unifies_lays_keys():
    assert normalize_brand("Lay's") == normalize_brand("lays")
    assert normalize_brand("Louis") == normalize_brand("lay's")


def test_planogram_brand_share_single_lays_key():
    rows = [
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Magic Masala",
            "expected_facings": 19,
            "actual_facings": 19,
            "expected_shelf_units": 19,
            "actual_visible_units": 13,
            "avg_daily_sales": 10,
            "match_status": "MATCHED",
        },
        {
            "brand": "lays",
            "product_name": "potato chips",
            "variant": "Spanish Tomato Tango",
            "expected_facings": 6,
            "actual_facings": 6,
            "expected_shelf_units": 6,
            "actual_visible_units": 6,
            "avg_daily_sales": 10,
            "match_status": "BRAND_MATCHED",
        },
    ]
    analysis = build_planogram_analysis(
        rows,
        count_validation={
            "total_actual_facings": {"status": "VERIFIED", "verified_value": 25},
            "total_actual_visible_units": {"status": "VERIFIED", "verified_value": 19},
        },
        unplanned_products=[
            {
                "brand": "Lay's",
                "product_name": "Extra",
                "actual_facings": 2,
            }
        ],
    )
    brands = {b["brand"]: b for b in analysis["brand_analysis"]}
    assert len(brands) == 1
    key = next(iter(brands))
    assert key in {"lays", "lay's"}
    assert brands[key]["actual_facings"] == 27  # 19+6+2
    assert brands[key]["expected_facings"] == 25


def test_single_sku_golden_metrics():
    row = build_planogram_row_metrics(
        {
            "expected_facings": 10,
            "actual_facings": 8,
            "min_facings": 8,
            "max_facings": 12,
            "expected_shelf_units": 20,
            "actual_visible_units": 14,
            "expected_mrp_inr": 20,
            "avg_daily_sales": 5,
        }
    )
    assert calculate_facing_compliance(8, 10).value == 80.0
    assert row["facing_variance"]["value"] == -2
    assert row["min_max_facing_status"] == "WITHIN_RANGE"
    assert row["shelf_unit_compliance"]["value"] == 70.0
    assert row["visible_unit_shortfall"]["value"] == 6
    assert row["potential_visible_unit_value_gap"]["value"] == 120.0
    assert calculate_visible_shelf_coverage_days(14, 5).value == 2.8


def test_two_sku_weighted_facing_compliance():
    rows = [
        {"actual_facings": 8, "expected_facings": 10},
        {"actual_facings": 4, "expected_facings": 5},
    ]
    assert calculate_facing_compliance_aggregate(rows).value == 80.0


def test_placeholder_sku_does_not_collapse_product_identities():
    assert normalize_product_identity("Lay's", "Potato chips", "Magic Masala", "UNVERIFIABLE") == (
        "lays|potato chips|magic masala"
    )
    assert normalize_product_identity("Lay's", "Potato chips", "UNVERIFIABLE", "UNVERIFIABLE") == (
        "lays|potato chips"
    )


def test_shelf_only_products_identified_keeps_split_variant_rows():
    products = [
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "Magic Masala",
            "sku": "UNVERIFIABLE",
            "actual_facings": 19,
            "actual_visible_units": 13,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "UNVERIFIABLE",
            "sku": "UNVERIFIABLE",
            "actual_facings": 6,
            "actual_visible_units": 6,
        },
        {
            "brand": "Lay's",
            "brand_status": "IDENTIFIED",
            "product_name": "Potato chips",
            "product_status": "IDENTIFIED",
            "variant": "UNVERIFIABLE",
            "sku": "UNVERIFIABLE",
            "actual_facings": 12,
            "actual_visible_units": 6,
        },
    ]
    analysis = build_shelf_only_analysis(
        products,
        count_validation={
            "total_actual_facings": {
                "status": "VERIFIED",
                "verified_value": 37,
            },
            "total_actual_visible_units": {
                "status": "VERIFIED",
                "verified_value": 25,
            },
        },
    )
    assert analysis["calculated_metrics"]["products_identified"]["value"] == 3
    assert analysis["calculated_metrics"]["brands_identified"]["value"] == 1
    assert analysis["calculated_metrics"]["variants_identified"]["value"] == 3


def test_canonicalize_louis_chips_to_lays():
    from app.cv_brand_canonicalize import canonicalize_shelf_cv_products

    products = [
        {"brand": "LOUIS", "product_name": "Chips", "variant": "Magic Masala"},
        {"brand": "LOUIS", "product_name": "Chips", "variant": "UNVERIFIABLE"},
    ]
    canonicalize_shelf_cv_products(products)
    assert products[0]["brand"] == "Lay's"
    assert products[1]["brand"] == "Lay's"
