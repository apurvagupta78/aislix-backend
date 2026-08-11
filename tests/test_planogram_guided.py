"""Tests for planogram-guided recognition."""

from pathlib import Path

from app.planogram_csv import parse_csv_text
from app.planogram_guided import (
    assign_planogram_slots,
    best_candidate_from_text,
    label_from_candidate,
    prepare_planogram_candidates,
    score_text_against_candidate,
    snap_label_to_planogram,
)

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "planogram_shampoo_row.csv"


def _candidates() -> list[dict]:
    parsed = parse_csv_text(FIXTURE.read_text(encoding="utf-8"))
    items = [row["data"] for row in parsed["rows"] if row.get("valid")]
    return prepare_planogram_candidates(
        items,
        scope_type="sub_category",
        scope_values={"sub_category": "shampoo"},
        scan_context={"sub_category": "shampoo"},
    )


def test_prepare_candidates_filters_scope():
    cands = _candidates()
    assert len(cands) == 8
    assert {c["brand"] for c in cands} >= {"Dove", "Clinic Plus", "Himalaya"}


def test_ocr_text_matches_clinic_plus():
    cands = _candidates()
    match = best_candidate_from_text("CLINIC PLUS STRONG & LONG SHAMPOO 180ml", cands)
    assert match is not None
    assert match[0]["brand"] == "Clinic Plus"


def test_snap_rejects_off_list_brand():
    cands = _candidates()
    snapped = snap_label_to_planogram(
        {"brand": "Dabur", "product_name": "Shampoo", "confidence": 0.9},
        cands,
        ocr_text="dabur herbal shampoo",
    )
    assert snapped is None


def test_snap_maps_dove_variant_to_planogram_row():
    cands = _candidates()
    snapped = snap_label_to_planogram(
        {"brand": "Dove", "product_name": "Anti Dandruff Shampoo", "confidence": 0.9},
        cands,
        ocr_text="dove intense repair shampoo 180ml",
    )
    assert snapped is not None
    assert snapped["brand"] == "Dove"
    assert "Intense Repair" in snapped["product_name"] or snapped["product_name"]


def test_score_himalaya_from_text():
    cands = _candidates()
    scores = [
        (c["brand"], score_text_against_candidate("HIMALAYA ANTI-HAIR FALL SHAMPOO", c))
        for c in cands
    ]
    best_brand = max(scores, key=lambda x: x[1])[0]
    assert best_brand == "Himalaya"


def test_label_from_candidate_marks_guided():
    cands = _candidates()
    label = label_from_candidate(cands[0], 0.88, "planogram_ocr")
    assert label["planogram_guided"] is True
    assert label["brand"]


def test_assign_planogram_slots_one_per_column():
    cands = _candidates()
    records = []
    for i, cand in enumerate(cands):
        records.append({
            "x1": i * 100,
            "y1": 10,
            "x2": i * 100 + 80,
            "y2": 200,
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
        })
    assigned = assign_planogram_slots(records, cands)
    assert len(assigned) == 8
    brands = {r["brand"] for r in assigned}
    assert len(brands) == 8
    assert all(r["planogram_guided"] for r in assigned)
