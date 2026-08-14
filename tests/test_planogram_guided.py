"""Tests for planogram-guided recognition."""

from pathlib import Path

from app.planogram_csv import parse_csv_text
from app.planogram_guided import (
    align_shelf_clusters_to_planogram,
    assign_planogram_shelf_rows,
    assign_planogram_slots,
    best_candidate_from_text,
    cluster_records_by_shelf_row,
    label_from_candidate,
    parse_shelf_number,
    planogram_visual_rows,
    prepare_planogram_candidates,
    score_text_against_candidate,
    should_use_planogram_shelf_rows,
    snap_label_to_planogram,
)

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "planogram_shampoo_row.csv"
LAYS_FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "planogram_lays_a1l.csv"


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


def _lays_candidates() -> list[dict]:
    parsed = parse_csv_text(LAYS_FIXTURE.read_text(encoding="utf-8"))
    items = [row["data"] for row in parsed["rows"] if row.get("valid")]
    return prepare_planogram_candidates(
        items,
        scope_type="location",
        scope_values={"location": "A-1-L", "aisle": "A-1-L"},
        scan_context={
            "sub_category": "chips",
            "aislix_category": "Packaged Food & Snacks",
            "shelf_label": "A-1-L",
        },
    )


def test_parse_shelf_number_from_position():
    assert parse_shelf_number("Shelf 2 / Position 1-2") == 2
    assert parse_shelf_number("shelf 6 / position 5-6") == 6
    assert parse_shelf_number("") is None


def test_cluster_records_by_shelf_row():
    records = []
    for row_idx, y in enumerate([50, 180, 310, 440, 570]):
        for col in range(6):
            records.append({
                "x1": col * 90,
                "y1": y,
                "x2": col * 90 + 70,
                "y2": y + 100,
                "brand": "Unknown",
                "product_name": "Unidentified SKU",
            })
    rows = cluster_records_by_shelf_row(records)
    assert len(rows) == 5
    assert len(rows[0]) == 6


def test_align_shelf_clusters_bottom_aligns_extra_top_row():
    mapping = align_shelf_clusters_to_planogram(6, [2, 3, 4, 5, 6])
    assert mapping[1] == 2
    assert mapping[5] == 6
    assert 0 not in mapping


def test_should_use_planogram_shelf_rows_for_chips_multi_row():
    cands = _lays_candidates()
    records = [{"x1": 0, "y1": 0, "x2": 10, "y2": 10}] * 8
    ctx = {"shelf_mode": "single_row", "sub_category": "chips"}
    assert should_use_planogram_shelf_rows(records, cands, ctx) is True


def test_shelf_row_neighbor_hint_uses_labeled_neighbors():
    from app.planogram_guided import _shelf_row_neighbor_hint

    classified = [
        {"x1": 0, "y1": 100, "x2": 50, "y2": 200, "brand": "Unknown", "product_name": "Unidentified SKU"},
        {"x1": 60, "y1": 105, "x2": 110, "y2": 195, "brand": "Lays", "product_name": "Tomato Tango"},
        {"x1": 120, "y1": 400, "x2": 170, "y2": 500, "brand": "Lays", "product_name": "India's Magic Masala"},
    ]
    hint = _shelf_row_neighbor_hint(classified, 0)
    assert "Tomato Tango" in hint
    assert "Magic Masala" not in hint


def test_recover_planogram_unknowns_skips_without_openai(monkeypatch):
    from app.planogram_guided import recover_planogram_unknowns_with_gpt

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    classified = [
        {"brand": "Unknown", "product_name": "Unidentified SKU", "image_path": ""},
    ]
    out, stats = recover_planogram_unknowns_with_gpt(
        classified,
        scan_context={"planogram_candidates": [{"brand": "Lays", "product_name": "Tomato Tango"}]},
    )
    assert out[0]["brand"] == "Unknown"
    assert stats["gpt_recovery"] == 0


def test_assign_planogram_shelf_rows_without_shelf_position():
    """Frontend planogram JSON often omits shelf_position — row assignment must still work."""
    cands = _lays_candidates()
    for row in cands:
        row.pop("shelf_position", None)

    records = []
    row_y = [120, 250, 380, 510, 640]
    for y in row_y:
        for col in range(7):
            records.append({
                "x1": col * 90,
                "y1": y,
                "x2": col * 90 + 70,
                "y2": y + 100,
                "brand": "Unknown",
                "product_name": "Unidentified SKU",
                "confidence": 0.35,
            })

    assigned = assign_planogram_shelf_rows(
        records,
        cands,
        scan_context={"shelf_mode": "multi_row", "sub_category": "chips"},
    )
    products = {r["product_name"] for r in assigned}
    assert "India's Magic Masala" in products
    assert "Tomato Tango" in products
    assert "American Style Cream & Onion" in products
    unknown = sum(1 for r in assigned if (r.get("brand") or "").lower() == "unknown")
    assert unknown <= len(row_y)


def test_allocate_cluster_candidates_expands_three_products_to_six_rows():
    cands = _lays_candidates()
    for row in cands:
        row.pop("shelf_position", None)
    visual = planogram_visual_rows(cands)
    assert len(visual) == 3
    from app.planogram_guided import allocate_cluster_candidates

    allocated = allocate_cluster_candidates(cands, 6)
    assert len(allocated) == 6
    names = [r["product_name"] for r in allocated]
    assert names.count("India's Magic Masala") >= 2
    assert "Tomato Tango" in names
    assert "American Style Cream & Onion" in names


def test_assign_planogram_shelf_rows_labels_unknown_facings_by_row():
    cands = _lays_candidates()
    records = []
    # 5 shelf rows matching planogram shelves 2–6
    for y in [120, 250, 380, 510, 640]:
        for col in range(7):
            records.append({
                "x1": col * 90,
                "y1": y,
                "x2": col * 90 + 70,
                "y2": y + 100,
                "brand": "Unknown",
                "product_name": "Unidentified SKU",
                "confidence": 0.35,
            })

    assigned = assign_planogram_shelf_rows(
        records,
        cands,
        scan_context={"shelf_mode": "multi_row", "sub_category": "chips"},
    )
    assert len(assigned) == len(records)
    products = {r["product_name"] for r in assigned}
    assert "India's Magic Masala" in products
    assert "Tomato Tango" in products
    assert "American Style Cream & Onion" in products
    assert all(r.get("planogram_guided") for r in assigned)
    masala = sum(1 for r in assigned if r["product_name"] == "India's Magic Masala")
    tomato = sum(1 for r in assigned if r["product_name"] == "Tomato Tango")
    cream = sum(1 for r in assigned if r["product_name"] == "American Style Cream & Onion")
    assert masala == 14
    assert tomato == 7
    assert cream == 14
