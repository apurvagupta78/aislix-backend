"""Tests for Luna secondary analysis gate + derivation."""

from app.luna_vision_scan import luna_required, run_luna_secondary_scan


def test_luna_required_for_planogram_mode():
    assert luna_required({"analysis_mode": "planogram_comparison"}) is True


def test_luna_required_for_mrp_rows():
    assert luna_required(
        {
            "analysis_mode": "shelf_only",
            "planogram_items": [{"brand": "Odol", "mrp_inr": 2.99}],
        }
    )


def test_luna_derives_from_astra_notes_instead_of_null():
    astra = {
        "products": [
            {
                "brand": "Odol",
                "product_name": "UNVERIFIABLE",
                "visual_notes": "Orange cartons with readable Odol branding near Rs 2.99 tag.",
                "actual_facings": 5,
            }
        ]
    }
    out = run_luna_secondary_scan(astra, {"analysis_mode": "planogram_comparison"})
    assert out is not None
    assert out["status"] == "derived_from_astra"
    assert isinstance(out["visible_prices"], list)
    assert out["visible_prices"]
    assert out["visible_prices"][0]["price"] == 2.99
