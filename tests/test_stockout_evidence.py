"""Stockout evidence state regression tests."""

from app.stockout_evidence import (
    CONFIRMED_INVENTORY_STOCKOUT,
    NOT_OBSERVED,
    SUSPECTED_SHELF_GAP,
    VERIFIED_SHELF_ABSENCE,
    classify_stockout_evidence,
    summarize_stockout_evidence,
)


def test_planogram_missing_is_verified_shelf_absence_not_inventory_stockout():
    state = classify_stockout_evidence(
        detected_qty=0,
        expected_on_shelf=True,
        planogram_missing=True,
        identity_resolved=True,
        photo_coverage_adequate=True,
        inventory_confirmed=False,
    )
    assert state == VERIFIED_SHELF_ABSENCE


def test_unresolved_target_is_suspected_not_confirmed():
    state = classify_stockout_evidence(
        detected_qty=0,
        expected_on_shelf=True,
        planogram_missing=True,
        identity_resolved=False,
        photo_coverage_adequate=True,
    )
    assert state == SUSPECTED_SHELF_GAP


def test_inventory_confirmed_only_produces_confirmed_stockout():
    state = classify_stockout_evidence(
        detected_qty=0,
        expected_on_shelf=True,
        planogram_missing=True,
        identity_resolved=True,
        inventory_confirmed=True,
    )
    assert state == CONFIRMED_INVENTORY_STOCKOUT


def test_inadequate_coverage_is_not_observed():
    state = classify_stockout_evidence(
        detected_qty=0,
        expected_on_shelf=True,
        planogram_missing=True,
        photo_coverage_adequate=False,
    )
    assert state == NOT_OBSERVED


def test_summarize_stockout_evidence():
    summary = summarize_stockout_evidence(
        [VERIFIED_SHELF_ABSENCE, SUSPECTED_SHELF_GAP, NOT_OBSERVED]
    )
    assert summary["verified_shelf_absence_count"] == 1
    assert summary["confirmed_oos_count"] == 1
