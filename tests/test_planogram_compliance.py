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
        "expected_qty": 1,
    })
    assert not errors
    assert row["match_key"].startswith("dove|")


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
