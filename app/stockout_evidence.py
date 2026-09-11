"""Stockout evidence states — photo observations must not imply inventory certainty."""

from __future__ import annotations

NOT_OBSERVED = "not_observed"
SUSPECTED_SHELF_GAP = "suspected_shelf_gap"
VERIFIED_SHELF_ABSENCE = "verified_shelf_absence"
CONFIRMED_INVENTORY_STOCKOUT = "confirmed_inventory_stockout"

STOCKOUT_STATES = frozenset(
    {
        NOT_OBSERVED,
        SUSPECTED_SHELF_GAP,
        VERIFIED_SHELF_ABSENCE,
        CONFIRMED_INVENTORY_STOCKOUT,
    }
)


def classify_stockout_evidence(
    *,
    detected_qty: int,
    expected_on_shelf: bool = False,
    planogram_missing: bool = False,
    identity_resolved: bool = True,
    photo_coverage_adequate: bool = True,
    inventory_confirmed: bool = False,
) -> str:
    """
    Map detection + context to an evidence state.

    A missing photo detection alone cannot produce confirmed_inventory_stockout.
    """
    if inventory_confirmed and expected_on_shelf and detected_qty <= 0:
        return CONFIRMED_INVENTORY_STOCKOUT
    if not photo_coverage_adequate:
        return NOT_OBSERVED
    if planogram_missing and expected_on_shelf and identity_resolved:
        return VERIFIED_SHELF_ABSENCE
    if expected_on_shelf and detected_qty <= 0 and not identity_resolved:
        return SUSPECTED_SHELF_GAP
    if detected_qty <= 0 and not expected_on_shelf:
        return SUSPECTED_SHELF_GAP
    return NOT_OBSERVED


def apply_stockout_evidence_to_metrics(
    metrics: dict,
    *,
    planogram_compliance: dict | None = None,
    planogram_items: list[dict] | None = None,
) -> None:
    """Merge planogram-backed absence evidence into metrics (mutates metrics)."""
    states: list[str] = []
    lines = (planogram_compliance or {}).get("lines") or []
    plano_by_key: dict[str, dict] = {}
    for item in planogram_items or []:
        brand = str(item.get("brand") or "").strip().lower()
        product = str(item.get("product_name") or item.get("product") or "").strip().lower()
        key = "|".join(p for p in (brand, product) if p)
        if key:
            plano_by_key[key] = item

    for line in lines:
        issue = str(line.get("issue_type") or "")
        if issue not in {"missing", "wrong_product", "wrong_category", "wrong_location"}:
            continue
        exp_brand = str(line.get("expected_brand") or "").strip().lower()
        exp_product = str(line.get("expected_product") or "").strip().lower()
        key = "|".join(p for p in (exp_brand, exp_product) if p)
        plano = plano_by_key.get(key) or {}
        sku = str(plano.get("sku") or plano.get("gtin") or "").strip()
        identity_resolved = bool(sku) or bool(exp_brand and exp_product)
        states.append(
            classify_stockout_evidence(
                detected_qty=int(line.get("actual_qty") or line.get("detected_qty") or 0),
                expected_on_shelf=True,
                planogram_missing=True,
                identity_resolved=identity_resolved,
                photo_coverage_adequate=True,
            )
        )

    if states:
        metrics.update(summarize_stockout_evidence(states))
    else:
        metrics.setdefault("confirmed_oos_count", 0)
        metrics.setdefault("verified_shelf_absence_count", 0)
        metrics.setdefault("suspected_shelf_gap_count", 0)


def summarize_stockout_evidence(states: list[str]) -> dict:
    """Aggregate evidence states for metrics payload."""
    counts = {state: 0 for state in STOCKOUT_STATES}
    for state in states:
        if state in counts:
            counts[state] += 1
    verified_absence = counts[VERIFIED_SHELF_ABSENCE]
    confirmed_inventory = counts[CONFIRMED_INVENTORY_STOCKOUT]
    suspected = counts[SUSPECTED_SHELF_GAP]
    not_obs = counts[NOT_OBSERVED]
    return {
        "stockout_evidence_states": counts,
        "verified_shelf_absence_count": verified_absence,
        "confirmed_inventory_stockout_count": confirmed_inventory,
        "suspected_shelf_gap_count": suspected,
        "not_observed_count": not_obs,
        # Legacy field: only verified/planogram-backed absences — not raw qty==0.
        "confirmed_oos_count": verified_absence + confirmed_inventory,
    }
