"""Tests for FNV QC disposition finalize (no shelf inventory required)."""

from __future__ import annotations

from app.fnv_qc import finalize_fnv_qc_result, is_fnv_qc_metadata, normalize_fnv_qc_metadata


def test_is_fnv_qc_from_analysis_mode():
    assert is_fnv_qc_metadata({"analysis_mode": "fnv_qc"}) is True
    assert is_fnv_qc_metadata({"purpose": "fnv_qc"}) is True
    assert is_fnv_qc_metadata({"analysis_mode": "shelf_only"}) is False


def test_normalize_sets_mode_and_skips_cache():
    meta = normalize_fnv_qc_metadata({"purpose": "fnv_qc"})
    assert meta["analysis_mode"] == "fnv_qc"
    assert meta["skip_reference_cache"] == "1"


def test_finalize_fnv_qc_from_disposition_json():
    parsed = {
        "raw": {
            "product": "Tomato",
            "category": "Produce",
            "disposition": "DAMAGED",
            "defect_types": ["Bruising", "Rot"],
            "confidence": 0.91,
            "notes": "Visible soft bruise",
        },
        "inventory": None,
        "facings": None,
    }
    out = finalize_fnv_qc_result(scan_id="abc", parsed=parsed, processing_ms=42)
    assert out["disposition"] == "DAMAGED"
    assert out["fnv_qc"]["defect_types"] == ["Bruising", "Rot"]
    assert out["analysis_mode"] == "fnv_qc"
    assert out["products"] == []
    assert out["metrics"]["processing_ms"] == 42


def test_finalize_fnv_qc_defaults_human_review():
    out = finalize_fnv_qc_result(
        scan_id="x",
        parsed={"raw": {"product": "Apple"}},
        processing_ms=1,
    )
    assert out["disposition"] == "HUMAN_REVIEW"


def test_finalize_fnv_qc_clears_defects_when_sellable():
    out = finalize_fnv_qc_result(
        scan_id="x",
        parsed={
            "raw": {
                "disposition": "SELLABLE",
                "defect_types": ["Rot"],
            }
        },
        processing_ms=1,
    )
    assert out["disposition"] == "SELLABLE"
    assert out["defect_types"] == []
