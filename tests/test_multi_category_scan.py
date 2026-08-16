"""Multi category·subcategory scan context and compliance."""

from __future__ import annotations

from app.scan_context import resolve_scan_context, selected_sub_category_ids
from app.subcategory_compliance import analyze_subcategory_compliance


def _facing(brand, product, **extra):
    row = {
        "brand": brand,
        "product_name": product,
        "variant": "",
        "category": "Personal Care",
        "confidence": 0.9,
        "pack_text": extra.pop("pack_text", ""),
    }
    row.update(extra)
    return row


def test_resolve_scan_context_parses_category_selections():
    ctx = resolve_scan_context(
        {
            "category": "Personal Care",
            "sub_category": "shampoo",
            "category_selections": [
                {
                    "category_name": "Personal Care",
                    "sub_category_id": "shampoo",
                    "sub_category_label": "Shampoo",
                },
                {
                    "category_name": "Personal Care",
                    "sub_category_id": "deodorant",
                    "sub_category_label": "Deodorant",
                },
                {
                    "category_name": "Personal Care",
                    "sub_category_id": "soap",
                    "sub_category_label": "Soap",
                },
            ],
        }
    )
    assert ctx["multi_sub_category_audit"] is True
    assert selected_sub_category_ids(ctx) == ["shampoo", "deodorant", "soap"]


def test_multi_pc_audit_allows_deodorant_and_soap():
    ctx = resolve_scan_context(
        {
            "category": "Personal Care",
            "sub_category": "shampoo",
            "category_selections": [
                {"category_name": "Personal Care", "sub_category_id": "shampoo", "sub_category_label": "Shampoo"},
                {"category_name": "Personal Care", "sub_category_id": "deodorant", "sub_category_label": "Deodorant"},
                {"category_name": "Personal Care", "sub_category_id": "soap", "sub_category_label": "Soap"},
            ],
        }
    )
    ctx["catalog_categories"] = ["personal care"]
    ctx["brand_hints"] = {"dove", "axe", "fogg", "pears", "dettol"}
    classified = [
        _facing("Axe", "Deodorant Body Spray", pack_text="deodorant body spray"),
        _facing("Pears", "Soap Bar", pack_text="soap bar"),
    ]
    result = analyze_subcategory_compliance(classified, ctx)
    assert result["misplaced_facings"] == 0
