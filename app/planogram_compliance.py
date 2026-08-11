"""Compare expected planogram data vs AI scan inventory."""

from __future__ import annotations

import re
from typing import Any

from app.inventory import _normalize_brand_key
from app.planogram_csv import build_match_key

ISSUE_CORRECT = "correct"
ISSUE_MISSING = "missing"
ISSUE_QTY_MISMATCH = "qty_mismatch"
ISSUE_WRONG_PRODUCT = "wrong_product"
ISSUE_WRONG_CATEGORY = "wrong_category"
ISSUE_WRONG_LOCATION = "wrong_location"
ISSUE_UNEXPECTED = "unexpected"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _token_overlap(a: str, b: str) -> float:
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _inventory_key(item: dict) -> str:
    brand = item.get("brand") or ""
    product = item.get("product_name") or item.get("name") or ""
    sku = item.get("sku") or ""
    return build_match_key(brand, product, sku)


def _brand_key(item: dict) -> str:
    return _normalize_brand_key(item.get("brand") or "", item.get("product_name") or item.get("name") or "")


def filter_planogram_by_scope(
    items: list[dict],
    scope_type: str | None,
    scope_values: dict | None,
    scan_context: dict | None = None,
) -> list[dict]:
    """Filter expected rows to assignment scope."""
    if not items:
        return []
    scope_values = scope_values or {}
    scan_context = scan_context or {}

    if not scope_type:
        return items

    if scope_type == "category":
        cat = _norm(scope_values.get("category") or scan_context.get("aislix_category") or "")
        return [i for i in items if _norm(i.get("category") or "") == cat or cat in _norm(i.get("category") or "")]

    if scope_type == "sub_category":
        sub = _norm(scope_values.get("sub_category") or scan_context.get("sub_category") or "")
        return [i for i in items if _norm(i.get("sub_category") or "") == sub]

    if scope_type == "location":
        aisle = _norm(scope_values.get("aisle") or scope_values.get("location") or scan_context.get("shelf_label") or "")
        return [
            i for i in items
            if aisle and (
                aisle in _norm(i.get("aisle") or "")
                or aisle in _norm(i.get("location") or "")
                or aisle == _norm(i.get("aisle") or "")
            )
        ]

    return items


def _match_score(expected: dict, actual: dict) -> float:
    exp_sku = _norm(expected.get("sku") or "")
    act_sku = _norm(actual.get("sku") or "")
    if exp_sku and act_sku and exp_sku == act_sku:
        return 1.0

    exp_brand = _brand_key({"brand": expected.get("brand"), "product_name": expected.get("product_name")})
    act_brand = _brand_key(actual)
    if exp_brand != act_brand and exp_brand not in act_brand and act_brand not in exp_brand:
        return 0.0

    product_score = _token_overlap(expected.get("product_name") or "", actual.get("product_name") or actual.get("name") or "")
    if product_score >= 0.5:
        return 0.6 + 0.4 * product_score

    exp_sub = _norm(expected.get("sub_category") or "")
    act_sub = _norm(actual.get("sub_category") or actual.get("category") or "")
    if exp_sub and act_sub and exp_sub == act_sub:
        return 0.55

    if exp_brand == act_brand:
        return 0.45

    return 0.0


def _find_best_match(expected: dict, inventory: list[dict], used: set[int]) -> tuple[int | None, float]:
    best_idx = None
    best_score = 0.0
    for idx, item in enumerate(inventory):
        if idx in used:
            continue
        score = _match_score(expected, item)
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_score < 0.45:
        return None, 0.0
    return best_idx, best_score


def _wrong_location_check(actual: dict, full_store_items: list[dict], current_aisle: str) -> dict | None:
    """True when product belongs to another aisle in the full store planogram."""
    if not full_store_items or not current_aisle:
        return None
    act_brand = _brand_key(actual)
    act_product = _norm(actual.get("product_name") or actual.get("name") or "")
    for row in full_store_items:
        row_aisle = _norm(row.get("aisle") or row.get("location") or "")
        if not row_aisle or row_aisle == _norm(current_aisle):
            continue
        if _brand_key(row) == act_brand and _token_overlap(row.get("product_name") or "", act_product) >= 0.4:
            return row
    return None


def _suggest_action(issue_type: str, line: dict) -> str:
    eb = line.get("expected_brand") or ""
    ep = line.get("expected_product") or ""
    ab = line.get("actual_brand") or ""
    ap = line.get("actual_product") or ""
    exp_qty = line.get("expected_qty") or 0
    act_qty = line.get("actual_qty") or 0
    delta = max(0, exp_qty - act_qty)
    detail = line.get("detail") or ""

    if issue_type == ISSUE_WRONG_LOCATION:
        return f"Move {ab} {ap} to the correct aisle ({detail or 'see planogram'})."
    if issue_type in {ISSUE_MISSING, ISSUE_QTY_MISMATCH}:
        return f"Replenish {eb} {ep} — {delta} unit(s) required."
    if issue_type == ISSUE_WRONG_CATEGORY:
        return f"Move {ab} {ap} to the correct category section ({detail or ep})."
    if issue_type == ISSUE_WRONG_PRODUCT:
        return f"Replace with expected product: {eb} {ep}."
    if issue_type == ISSUE_UNEXPECTED:
        return f"Review unexpected product: {ab} {ap}."
    return "No action required."


def compare_planogram(
    planogram_items: list[dict],
    inventory: list[dict],
    scan_context: dict | None = None,
    scope_type: str | None = None,
    scope_values: dict | None = None,
    full_store_items: list[dict] | None = None,
) -> dict[str, Any]:
    """Compare expected planogram rows vs detected inventory."""
    scan_context = scan_context or {}
    scoped_expected = filter_planogram_by_scope(planogram_items, scope_type, scope_values, scan_context)
    full_store = full_store_items or planogram_items
    current_aisle = (
        scan_context.get("shelf_label")
        or scan_context.get("location")
        or (scope_values or {}).get("aisle")
        or ""
    )

    used_actual: set[int] = set()
    lines: list[dict] = []

    for expected in scoped_expected:
        idx, score = _find_best_match(expected, inventory, used_actual)
        exp_qty = int(expected.get("expected_qty") or 0)
        exp_brand = expected.get("brand") or ""
        exp_product = expected.get("product_name") or ""

        if idx is None:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_MISSING,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": None,
                "actual_product": None,
                "actual_qty": 0,
                "severity": SEVERITY_CRITICAL if exp_qty > 0 else SEVERITY_WARNING,
                "detail": f"Expected {exp_qty}, found 0",
            })
            continue

        used_actual.add(idx)
        actual = inventory[idx]
        act_qty = int(actual.get("quantity") or actual.get("facings") or 0)
        act_brand = actual.get("brand") or ""
        act_product = actual.get("product_name") or actual.get("name") or ""

        wrong_cat = False
        exp_sub = _norm(expected.get("sub_category") or "")
        act_sub = _norm(scan_context.get("sub_category") or actual.get("sub_category") or "")
        if exp_sub and act_sub and exp_sub != act_sub:
            wrong_cat = True

        wrong_loc_row = _wrong_location_check(actual, full_store, current_aisle)

        if wrong_loc_row:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_WRONG_LOCATION,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": act_brand,
                "actual_product": act_product,
                "actual_qty": act_qty,
                "severity": SEVERITY_CRITICAL,
                "detail": wrong_loc_row.get("aisle") or wrong_loc_row.get("location") or "",
            })
        elif wrong_cat:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_WRONG_CATEGORY,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": act_brand,
                "actual_product": act_product,
                "actual_qty": act_qty,
                "severity": SEVERITY_CRITICAL,
                "detail": f"Expected sub-category {expected.get('sub_category')}",
            })
        elif score < 0.6:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_WRONG_PRODUCT,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": act_brand,
                "actual_product": act_product,
                "actual_qty": act_qty,
                "severity": SEVERITY_WARNING,
                "detail": "Detected product does not match expected SKU/name",
            })
        elif act_qty < exp_qty:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_QTY_MISMATCH,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": act_brand,
                "actual_product": act_product,
                "actual_qty": act_qty,
                "severity": SEVERITY_WARNING,
                "detail": f"Expected {exp_qty}, found {act_qty}",
            })
        else:
            lines.append({
                "planogram_item_id": expected.get("id"),
                "issue_type": ISSUE_CORRECT,
                "expected_brand": exp_brand,
                "expected_product": exp_product,
                "expected_qty": exp_qty,
                "actual_brand": act_brand,
                "actual_product": act_product,
                "actual_qty": act_qty,
                "severity": SEVERITY_INFO,
                "detail": "OK",
            })

    for idx, actual in enumerate(inventory):
        if idx in used_actual:
            continue
        act_brand = actual.get("brand") or ""
        act_product = actual.get("product_name") or actual.get("name") or ""
        if _norm(act_brand) in {"", "unknown"} and _norm(act_product) in {"", "unknown", "unidentified sku"}:
            continue
        lines.append({
            "planogram_item_id": None,
            "issue_type": ISSUE_UNEXPECTED,
            "expected_brand": None,
            "expected_product": None,
            "expected_qty": 0,
            "actual_brand": act_brand,
            "actual_product": act_product,
            "actual_qty": int(actual.get("quantity") or actual.get("facings") or 0),
            "severity": SEVERITY_WARNING,
            "detail": "Not in expected planogram for this assignment",
        })

    summary = {
        "expected_products": len(scoped_expected),
        "products_found": sum(1 for ln in lines if ln["issue_type"] != ISSUE_MISSING),
        "missing_products": sum(1 for ln in lines if ln["issue_type"] == ISSUE_MISSING),
        "quantity_issues": sum(1 for ln in lines if ln["issue_type"] == ISSUE_QTY_MISMATCH),
        "wrong_products": sum(1 for ln in lines if ln["issue_type"] == ISSUE_WRONG_PRODUCT),
        "wrong_category": sum(1 for ln in lines if ln["issue_type"] == ISSUE_WRONG_CATEGORY),
        "wrong_location": sum(1 for ln in lines if ln["issue_type"] == ISSUE_WRONG_LOCATION),
        "unexpected_products": sum(1 for ln in lines if ln["issue_type"] == ISSUE_UNEXPECTED),
        "correct_products": sum(1 for ln in lines if ln["issue_type"] == ISSUE_CORRECT),
    }

    total_checks = len(scoped_expected) or 1
    correct_weight = summary["correct_products"]
    compliance_percent = round(100.0 * correct_weight / total_checks, 2)

    corrective_actions = [
        {
            "issue_type": ln["issue_type"],
            "suggestion": _suggest_action(ln["issue_type"], ln),
            "status": "open",
            "comparison_line": ln,
        }
        for ln in lines
        if ln["issue_type"] != ISSUE_CORRECT
    ]

    # Attach expected_facings hints for detected_products sync (Lovable)
    inventory_expected_map = {}
    for ln in lines:
        if ln.get("actual_brand") and ln.get("expected_qty"):
            key = build_match_key(ln.get("actual_brand") or "", ln.get("actual_product") or "")
            inventory_expected_map[key] = ln.get("expected_qty")

    return {
        "compliance_percent": compliance_percent,
        "summary": summary,
        "lines": lines,
        "corrective_actions": corrective_actions,
        "scan_status": "needs_attention" if corrective_actions else "compliant",
        "inventory_expected_map": inventory_expected_map,
    }
