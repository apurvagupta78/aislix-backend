"""Regression tests for PC pack-text guard — no shampoo leakage onto soap/deo rows."""

from __future__ import annotations

from app.pc_pack_text_guard import (
    enforce_pc_pack_text_labels,
    infer_pc_product_type,
    pc_pack_text_conflicts_label,
    pc_propagation_allowed,
    reconcile_pc_rows_by_type,
)
from app.pc_row_recovery import recover_pc_unknowns_by_row


def _pc_ctx(**extra) -> dict:
    return {
        "aislix_category": "Personal Care",
        "multi_sub_category_audit": True,
        "shelf_mode": "multi_row",
        **extra,
    }


def test_weak_fragments_do_not_infer_shampoo():
    assert infer_pc_product_type("poo") is None
    assert infer_pc_product_type("anti d.") is None
    assert infer_pc_product_type("sham") is None


def test_soap_pack_conflicts_with_shampoo_label():
    label = {"brand": "Dove", "product_name": "Anti Dandruff Shampoo"}
    assert pc_pack_text_conflicts_label(label, "Dove Beauty Bar Soap Pure Gentle") is True


def test_deodorant_pack_conflicts_with_shampoo_label():
    label = {"brand": "Axe", "product_name": "Intense Repair Shampoo"}
    assert pc_pack_text_conflicts_label(label, "Axe Deodorant Body Spray Dark Temptation") is True


def test_shampoo_pack_does_not_conflict_with_shampoo_label():
    label = {"brand": "Dove", "product_name": "Anti Dandruff Shampoo"}
    assert pc_pack_text_conflicts_label(label, "Dove Anti Dandruff Solutions Shampoo") is False


def test_enforce_rejects_propagated_shampoo_on_soap_without_pack_text():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "",
            "recognition_source": "propagate",
            "confidence": 0.88,
        }
    ]
    out, stats = enforce_pc_pack_text_labels(classified, _pc_ctx())
    assert stats["pc_pack_text_reject"] == 1
    assert out[0]["brand"] == "Unknown"
    assert out[0]["recognition_source"] == "pc_pack_text_reject"


def test_enforce_fixes_soap_from_pack_ocr():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "Dove Beauty Bar Soap Pure and Gentle",
            "recognition_source": "faiss",
            "confidence": 0.9,
        }
    ]
    out, stats = enforce_pc_pack_text_labels(classified, _pc_ctx())
    assert stats["pc_pack_text_fix"] + stats["pc_pack_text_reject"] >= 1
    if stats["pc_pack_text_fix"]:
        assert "soap" in (out[0].get("product_name") or "").lower() or out[0]["brand"].lower() == "dove"


def test_enforce_rejects_shampoo_label_when_pack_says_soap_and_no_fix():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "Lux Soft Touch Soap",
            "recognition_source": "propagate",
            "confidence": 0.85,
        }
    ]
    out, stats = enforce_pc_pack_text_labels(classified, _pc_ctx())
    assert stats["pc_pack_text_reject"] == 1 or stats["pc_pack_text_fix"] == 1
    if stats["pc_pack_text_reject"]:
        assert out[0]["brand"] == "Unknown"


def test_pc_propagation_blocked_on_soap_pack():
    ref = {"brand": "Dove", "product_name": "Anti Dandruff Shampoo"}
    assert pc_propagation_allowed(ref, "Dove Beauty Bar Soap", _pc_ctx()) is False


def test_pc_propagation_allowed_on_matching_shampoo_pack():
    ref = {"brand": "Dove", "product_name": "Anti Dandruff Shampoo"}
    assert pc_propagation_allowed(ref, "Dove Anti Dandruff Solutions Shampoo 180ml", _pc_ctx()) is True


def test_row_recovery_does_not_copy_shampoo_to_soap_neighbor():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "dove shampoo",
            "y1": 10,
            "y2": 50,
            "x1": 0,
            "x2": 40,
        },
        {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "pack_text": "Dove Beauty Bar Soap Pure Gentle",
            "y1": 12,
            "y2": 52,
            "x1": 50,
            "x2": 90,
        },
    ]
    out, stats = recover_pc_unknowns_by_row(classified, _pc_ctx())
    assert stats["pc_row_recovery"] == 0
    assert out[1]["brand"] == "Unknown"


def test_row_recovery_copies_when_pack_supports_neighbor():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Beauty Bar Soap",
            "pack_text": "dove beauty bar soap",
            "y1": 10,
            "y2": 50,
            "x1": 0,
            "x2": 40,
        },
        {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "pack_text": "Dove Pure Gentle Beauty Bar",
            "y1": 12,
            "y2": 52,
            "x1": 50,
            "x2": 90,
        },
    ]
    out, stats = recover_pc_unknowns_by_row(classified, _pc_ctx())
    assert stats["pc_row_recovery"] == 1
    assert "soap" in (out[1].get("product_name") or "").lower() or out[1]["brand"] == "Dove"


def test_row_type_reconcile_removes_shampoo_on_soap_row():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Beauty Bar Soap",
            "pack_text": "dove beauty bar soap",
            "y1": 400,
            "y2": 450,
            "x1": 0,
            "x2": 40,
        },
        {
            "brand": "Dove",
            "product_name": "Beauty Bar Soap",
            "pack_text": "dove pure gentle soap",
            "y1": 402,
            "y2": 452,
            "x1": 50,
            "x2": 90,
        },
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "dove gentle",
            "y1": 405,
            "y2": 455,
            "x1": 100,
            "x2": 140,
        },
    ]
    out, stats = reconcile_pc_rows_by_type(classified, _pc_ctx())
    assert stats["pc_row_type_fix"] >= 1
    shampoo_on_soap = [
        r
        for r in out
        if "shampoo" in (r.get("product_name") or "").lower() and r["y1"] > 390
    ]
    assert not shampoo_on_soap


def test_typed_fallback_for_lux_soap_pack():
    from app.pc_pack_text_guard import _typed_fallback_label

    label = _typed_fallback_label(
        {"brand": "Unknown"},
        "Lux Soft Touch Soap 125g",
        _pc_ctx(),
        row_type="soap",
    )
    assert label is not None
    assert label["brand"] == "Lux"
    assert "soap" in label["product_name"].lower()


def test_tresemme_never_becomes_deodorant_fallback():
    from app.pc_pack_text_guard import _typed_fallback_label

    label = _typed_fallback_label(
        {"brand": "Tresemme", "product_name": "Smooth Shine Shampoo"},
        "tresemme smooth shine",
        _pc_ctx(),
        row_type="deodorant",
    )
    assert label is not None
    assert "deodorant" not in (label.get("product_name") or "").lower()
    assert "shampoo" in (label.get("product_name") or "").lower()


def test_guard_disabled_on_single_bin_shampoo_scan():
    classified = [
        {
            "brand": "Dove",
            "product_name": "Anti Dandruff Shampoo",
            "pack_text": "",
            "recognition_source": "propagate",
            "confidence": 0.88,
        }
    ]
    ctx = {"aislix_category": "Personal Care", "sub_category": "shampoo", "shelf_mode": "single_bin"}
    out, stats = enforce_pc_pack_text_labels(classified, ctx)
    assert stats["pc_pack_text_reject"] == 0
    assert out[0]["brand"] == "Dove"
