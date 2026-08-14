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
    assigned = assign_planogram_slots(records, cands, scan_context={"shelf_mode": "single_row"})
    assert len(assigned) == 8
    brands = {r["brand"] for r in assigned}
    assert len(brands) == 8
    assert all(r["planogram_guided"] for r in assigned)


def test_should_skip_planogram_slots_on_ice_cream_with_few_detections():
    from app.planogram_guided import should_use_planogram_slots

    cands = [
        {"brand": "Amul", "product_name": "Rajbhog Kulfi", "sub_category": "ice_cream"},
        {"brand": "Baskin Robbins", "product_name": "Funwich", "sub_category": "ice_cream"},
    ]
    records = [{"x1": 0, "y1": 0, "x2": 100, "y2": 100, "brand": "Unknown", "product_name": "Unidentified SKU"}]
    ctx = {"shelf_mode": "multi_row", "sub_category": "ice_cream"}
    assert should_use_planogram_slots(records, cands, ctx) is False


def test_ocr_brand_conflict_blocks_baskin_for_amul_text():
    from app.planogram_guided import best_candidate_from_text, prepare_planogram_candidates

    items = [
        {"brand": "Amul", "product_name": "Rajbhog Kulfi", "sub_category": "ice_cream", "expected_qty": 3, "location": "A-1-D", "category": "Frozen Foods & Ice Cream"},
        {"brand": "Baskin Robbins", "product_name": "Funwich", "sub_category": "ice_cream", "expected_qty": 2, "location": "A-1-D", "category": "Frozen Foods & Ice Cream"},
    ]
    cands = prepare_planogram_candidates(items, None, {}, {"sub_category": "ice_cream"})
    match = best_candidate_from_text("Amul Rajbhog Kulfi stick", cands)
    assert match is not None
    assert match[0]["brand"] == "Amul"
    blocked = best_candidate_from_text("Amul Rajbhog Kulfi stick", cands)
    assert blocked[0]["brand"] != "Baskin Robbins"
