"""Brand share calculations for dashboard + landing parity."""

from __future__ import annotations

from app.metrics import brand_share, build_brand_share_payload


def _toothpaste_inventory() -> list[dict]:
    rows = [
        ("Colgate", 12),
        ("Oral-B", 12),
        ("Closeup", 8),
        ("Colgate", 6),
        ("Colgate", 6),
        ("Odol", 6),
        ("Colgate", 6),
        ("Doctor", 6),
        ("Doctor", 6),
        ("Colgate", 6),
        ("Oral-B", 6),
        ("Oral-B", 6),
        ("Sensodyne", 6),
        ("Colgate", 6),
        ("Kolynos", 6),
        ("Unknown", 6, "category_mismatch"),
        ("Frau", 6, "category_mismatch"),
    ]
    inventory: list[dict] = []
    for row in rows:
        brand, qty = row[0], row[1]
        status = row[2] if len(row) > 2 else "ok"
        inventory.append(
            {
                "brand": brand,
                "product_name": "Toothpaste" if brand != "Frau" else "Water",
                "quantity": qty,
                "compliance_status": status,
                "counted_in_totals": True,
            }
        )
    return inventory


def test_brand_share_all_visible_includes_mismatches():
    shares = brand_share(_toothpaste_inventory(), exclude_category_mismatch=False)
    by_brand = {row["brand"]: row for row in shares}
    assert by_brand["Colgate"]["share"] == 36.2
    assert by_brand["Unknown"]["share"] == 5.2
    assert by_brand["Frau"]["share"] == 5.2
    assert sum(row["quantity"] for row in shares) == 116


def test_brand_share_in_audit_excludes_mismatches():
    shares = brand_share(_toothpaste_inventory(), exclude_category_mismatch=True)
    by_brand = {row["brand"]: row for row in shares}
    assert "Unknown" not in by_brand
    assert "Frau" not in by_brand
    assert by_brand["Colgate"]["share"] == 40.4
    assert by_brand["Oral-B"]["share"] == 23.1
    assert sum(row["quantity"] for row in shares) == 104


def test_build_brand_share_payload_uses_in_audit_when_sub_category_set():
    payload = build_brand_share_payload(_toothpaste_inventory(), audit_sub_category="toothpaste")
    assert payload["brand_share_scope"] == "in_audit"
    assert payload["brand_share_denominator"] == 104
    assert payload["top_brands"][0]["brand"] == "Colgate"
    assert payload["top_brands"][0]["share"] == 40.4
    assert payload["brand_share_all"][0]["share"] == 36.2
