"""Tests for planogram CSV parsing and compliance comparison."""

from pathlib import Path

from app.planogram_compliance import (
    ISSUE_CORRECT,
    ISSUE_MISSING,
    ISSUE_QTY_MISMATCH,
    ISSUE_UNEXPECTED,
    compare_planogram,
)
from app.planogram_csv import normalize_planogram_row, parse_csv_text

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "planogram_shampoo_row.csv"


def _load_fixture_items() -> list[dict]:
    parsed = parse_csv_text(FIXTURE.read_text(encoding="utf-8"))
    assert parsed["valid_count"] == 8
    return [row["data"] for row in parsed["rows"] if row.get("valid")]


def test_parse_shampoo_fixture_csv():
    parsed = parse_csv_text(FIXTURE.read_text(encoding="utf-8"))
    assert parsed["valid_count"] == 8
    assert parsed["error_count"] == 0
    brands = {row["data"]["brand"] for row in parsed["rows"] if row.get("valid")}
    assert "Dove" in brands
    assert "Clinic Plus" in brands


def test_normalize_manual_row():
    row, errors = normalize_planogram_row({
        "location": "Store 01",
        "aisle": "A-1-Z",
        "category": "Personal Care",
        "sub_category": "Shampoo",
        "brand": "Dove",
        "product_name": "Intense Repair Shampoo",
        "variant": "340ml",
        "expected_qty": 1,
    })
    assert not errors
    assert row["match_key"].startswith("dove|")
    assert row["variant"] == "340ml"


def test_normalize_requires_location_and_sub_category():
    _, errors = normalize_planogram_row({
        "category": "Personal Care",
        "brand": "Dove",
        "product_name": "Shampoo",
        "expected_qty": 1,
    })
    assert any("location is required" in e for e in errors)
    assert any("sub_category is required" in e for e in errors)


def test_parse_csv_missing_required_header():
    parsed = parse_csv_text("brand,product_name,expected_qty\nDove,Shampoo,1\n")
    assert parsed["valid_count"] == 0
    assert any("location" in e.lower() for e in parsed["errors"])


def test_compare_all_correct():
    expected = _load_fixture_items()
    inventory = [
        {"brand": item["brand"], "product_name": item["product_name"], "quantity": 1}
        for item in expected
    ]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "shampoo", "shelf_label": "A-1-Z"},
        scope_type="sub_category",
        scope_values={"sub_category": "shampoo"},
    )
    assert result["compliance_percent"] == 100.0
    assert result["summary"]["correct_products"] == 8
    assert result["scan_status"] == "compliant"


def test_compare_missing_and_unexpected():
    expected = _load_fixture_items()
    inventory = [
        {"brand": "Dove", "product_name": "Intense Repair Shampoo", "quantity": 1},
        {"brand": "Sunsilk", "product_name": "Long & Healthy Growth Shampoo", "quantity": 1},
        {"brand": "Colgate", "product_name": "Toothpaste", "quantity": 1},
    ]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "shampoo", "shelf_label": "A-1-Z"},
        scope_type="sub_category",
        scope_values={"sub_category": "shampoo"},
    )
    assert result["summary"]["missing_products"] >= 5
    assert result["summary"]["unexpected_products"] >= 1
    assert result["scan_status"] == "needs_attention"
    issue_types = {ln["issue_type"] for ln in result["lines"]}
    assert ISSUE_MISSING in issue_types
    assert ISSUE_UNEXPECTED in issue_types


def test_compare_qty_mismatch():
    expected = [{"brand": "Dove", "product_name": "Shampoo", "expected_qty": 6, "sub_category": "shampoo", "category": "Personal Care"}]
    inventory = [{"brand": "Dove", "product_name": "Shampoo", "quantity": 3}]
    result = compare_planogram(expected, inventory)
    qty_lines = [ln for ln in result["lines"] if ln["issue_type"] == ISSUE_QTY_MISMATCH]
    assert len(qty_lines) == 1
    assert qty_lines[0]["actual_qty"] == 3
    assert qty_lines[0]["expected_qty"] == 6


def test_corrective_actions_generated():
    expected = _load_fixture_items()[:1]
    inventory = []
    result = compare_planogram(expected, inventory)
    assert result["corrective_actions"]
    assert "Replenish" in result["corrective_actions"][0]["suggestion"]


def test_brand_shampoo_variant_counts_as_correct():
    """OCR variant name differs but same brand + shampoo type on shelf."""
    expected = [{
        "brand": "Dove",
        "product_name": "Nutritive",
        "expected_qty": 1,
        "sub_category": "Shampoo",
        "category": "Personal Care",
    }]
    inventory = [{
        "brand": "Dove",
        "product_name": "Anti Dandruff Solutions Dandruff Clean Fresh Shampoo",
        "quantity": 1,
    }]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "shampoo"},
    )
    assert result["compliance_percent"] == 100.0
    assert result["lines"][0]["issue_type"] == ISSUE_CORRECT


def test_conditioner_on_shampoo_row_is_wrong_product():
    expected = [{
        "brand": "L'Oreal",
        "product_name": "Total Repair 5 Shampoo",
        "expected_qty": 1,
        "sub_category": "Shampoo",
        "category": "Personal Care",
    }]
    inventory = [{
        "brand": "Loreal",
        "product_name": "Paris Color Protect Conditioner",
        "quantity": 1,
    }]
    result = compare_planogram(expected, inventory, scan_context={"sub_category": "shampoo"})
    assert result["lines"][0]["issue_type"] != ISSUE_CORRECT


def test_qty_over_expected_is_mismatch():
    expected = [{
        "brand": "Tresemme",
        "product_name": "Smooth & Shine Shampoo",
        "expected_qty": 1,
        "sub_category": "Shampoo",
        "category": "Personal Care",
    }]
    inventory = [{"brand": "Tresemme", "product_name": "Smooth Shine Shampoo", "quantity": 2}]
    result = compare_planogram(expected, inventory, scan_context={"sub_category": "shampoo"})
    assert result["lines"][0]["issue_type"] == ISSUE_QTY_MISMATCH
    assert result["lines"][0]["actual_qty"] == 2


def test_sub_categories_match_across_all_label_and_id_formats():
    from app.scan_context import sub_categories_match

    pairs = [
        ("ice_cream", "Ice cream"),
        ("soft_drinks", "Soft drinks"),
        ("tea", "Tea"),
        ("shampoo", "Shampoo"),
        ("hair_fall_control", "Hair Fall Control"),  # unknown → slug match
        ("frozen_vegetables", "Frozen vegetables"),
    ]
    for a, b in pairs:
        assert sub_categories_match(a, b), f"{a!r} should match {b!r}"


def test_planogram_tea_label_with_tea_id_scan_context():
    expected = [{
        "brand": "Tata",
        "product_name": "Tea Premium",
        "expected_qty": 1,
        "sub_category": "Tea",
        "category": "Beverages",
        "location": "A-1-S",
    }]
    inventory = [{"brand": "Tata", "product_name": "Tea Premium", "quantity": 1}]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "tea", "aislix_category": "Beverages", "shelf_label": "A-1-S"},
    )
    assert result["lines"][0]["issue_type"] == ISSUE_CORRECT


def test_ice_cream_subcategory_label_matches_slug():
    """Planogram rows use label 'Ice cream'; scan sends sub_category id ice_cream."""
    expected = [{
        "brand": "Amul",
        "product_name": "Kulfi",
        "expected_qty": 1,
        "sub_category": "Ice cream",
        "category": "Frozen Foods & Ice Cream",
        "location": "A-1-S",
    }]
    inventory = [{"brand": "Amul", "product_name": "Kulfi", "quantity": 1}]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "ice_cream", "shelf_label": "A-1-S"},
    )
    assert result["lines"][0]["issue_type"] == ISSUE_CORRECT
    assert result["compliance_percent"] == 100.0


def test_ice_cream_subcategory_compliance_not_cross_aisle():
    from app.subcategory_compliance import analyze_subcategory_compliance

    classified = [{
        "brand": "Amul",
        "product_name": "Kulfi",
        "category": "Frozen Foods & Ice Cream",
        "confidence": 0.9,
        "x1": 0, "y1": 0, "x2": 10, "y2": 10,
    }]
    ctx = {
        "aislix_category": "Frozen Foods & Ice Cream",
        "sub_category": "ice_cream",
        "sub_category_label": "Ice cream",
        "catalog_categories": ["dairy", "general"],
        "brand_hints": {"amul", "baskin robbins", "brooklyn"},
    }
    out = analyze_subcategory_compliance(classified, ctx)
    assert out["misplaced_facings"] == 0
    assert classified[0].get("subcategory_match") is True


def test_shampoo_row_realistic_inventory_compliance():
    """Simulate Hello's scan inventory vs 8-bottle fixture — should beat 13%."""
    expected = _load_fixture_items()
    inventory = [
        {"brand": "Unknown", "product_name": "Unidentified SKU", "quantity": 6},
        {"brand": "Tresemme", "product_name": "Smooth Shine Shampoo", "quantity": 2},
        {"brand": "Tresemme", "product_name": "Keratin Smooth Shampoo", "quantity": 1},
        {"brand": "Loreal", "product_name": "Paris Color Protect Conditioner", "quantity": 1},
        {"brand": "Head & Shoulders", "product_name": "Shampoo", "quantity": 1},
        {"brand": "Sunsilk", "product_name": "Nourishing Soft Smooth Shampoo With Egg Protein", "quantity": 1},
        {"brand": "Pantene", "product_name": "2 In 1 Hairfall Control Shampoo Conditioner", "quantity": 1},
        {"brand": "Dove", "product_name": "Anti Dandruff Solutions Dandruff Clean Fresh Shampoo", "quantity": 1},
        {"brand": "Dove", "product_name": "Daily Shine Conditioner", "quantity": 1},
    ]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "shampoo", "shelf_label": "A-1-Z"},
        scope_type="category",
        scope_values={"category": "Personal Care"},
    )
    assert result["compliance_percent"] >= 50.0
    assert result["summary"]["wrong_products"] <= 2


CHIPS_FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "planogram_chips_rack.csv"


def _load_chips_fixture_items() -> list[dict]:
    parsed = parse_csv_text(CHIPS_FIXTURE.read_bytes().decode("utf-8-sig"))
    assert parsed["valid_count"] == 20, parsed["errors"]
    return [row["data"] for row in parsed["rows"] if row.get("valid")]


def test_chips_planogram_csv_parses_with_bom_and_snacks_category():
    parsed = parse_csv_text(CHIPS_FIXTURE.read_bytes().decode("utf-8-sig"))
    assert parsed["valid_count"] == 20
    first = parsed["rows"][0]["data"]
    assert first["category"] == "Packaged Food & Snacks"
    assert first["sub_category"] == "potato_chips"


def test_chips_planogram_scopes_to_chips_audit():
    from app.planogram_guided import prepare_planogram_candidates

    items = _load_chips_fixture_items()
    ctx = {
        "aislix_category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "shelf_label": "Rack 01",
    }
    scoped = prepare_planogram_candidates(
        items,
        "sub_category",
        {"sub_category": "chips"},
        ctx,
    )
    assert len(scoped) == 20


def test_chips_subtypes_match_chips_audit():
    from app.scan_context import sub_categories_match

    assert sub_categories_match("potato_chips", "chips")
    assert sub_categories_match("tortilla_chips", "chips")
    assert sub_categories_match("extruded_snacks", "chips")
    assert sub_categories_match("namkeen", "chips")


def test_chips_planogram_no_false_wrong_category_on_mixed_rack():
    expected = _load_chips_fixture_items()
    picks = [row for row in expected if row["brand"] in {"Doritos", "Kurkure", "Balaji"}][:3]
    inventory = [
        {"brand": row["brand"], "product_name": row["product_name"], "quantity": 2}
        for row in picks
    ]
    result = compare_planogram(
        picks,
        inventory,
        scan_context={
            "sub_category": "chips",
            "aislix_category": "Packaged Food & Snacks",
            "shelf_label": "Rack 01",
        },
    )
    assert result["summary"]["wrong_category"] == 0
    assert result["summary"]["correct_products"] == 3


def test_chips_planogram_full_rack_inventory_compliance():
    """Simulate ideal chips rack: 20 SKUs × 2 facings."""
    expected = _load_chips_fixture_items()
    inventory = [
        {"brand": row["brand"], "product_name": row["product_name"], "quantity": row["expected_qty"]}
        for row in expected
    ]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={
            "sub_category": "chips",
            "aislix_category": "Packaged Food & Snacks",
            "shelf_label": "Rack 01",
        },
        scope_type="sub_category",
        scope_values={"sub_category": "chips"},
    )
    assert result["compliance_percent"] == 100.0
    assert result["summary"]["wrong_category"] == 0
    assert result["scan_status"] == "compliant"


def test_lays_planogram_product_level_compliance_not_zero_on_three_skus():
    """16 slot rows collapse to 3 products — compliance must not show 0% when all 3 SKUs found."""
    expected = [
        {"brand": "Lay's", "product_name": "India's Magic Masala", "expected_qty": 2, "sub_category": "Chips"},
        {"brand": "Lay's", "product_name": "India's Magic Masala", "expected_qty": 2, "sub_category": "Chips"},
        {"brand": "Lay's", "product_name": "Tomato Tango", "expected_qty": 2, "sub_category": "Chips"},
        {"brand": "Lay's", "product_name": "American Style Cream & Onion", "expected_qty": 2, "sub_category": "Chips"},
    ]
    inventory = [
        {"brand": "Lays", "product_name": "Indias Magic Masala Potato Chips", "quantity": 18},
        {"brand": "Lays", "product_name": "Tomato Tango Potato Chips", "quantity": 6},
        {"brand": "Lays", "product_name": "American Style Cream and Onion Potato Chips", "quantity": 12},
    ]
    result = compare_planogram(
        expected,
        inventory,
        scan_context={"sub_category": "chips", "aislix_category": "Packaged Food & Snacks", "location": "A-1-L"},
    )
    assert result["summary"]["expected_products"] == 3
    assert result["summary"]["missing_products"] == 0
    assert result["planogram_sku_match_percent"] == 100.0
    assert result["compliance_percent"] == 100.0
    assert result["planogram_qty_compliance_percent"] >= 75.0

