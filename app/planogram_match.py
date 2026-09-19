"""Join planogram expected state with Astra CV actual state."""

from __future__ import annotations

import re
from typing import Any

from app.planogram_csv import build_match_key

_MATCH_THRESHOLD = 0.72


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _cv_identity(row: dict[str, Any]) -> str:
    return build_match_key(
        str(row.get("brand") or ""),
        str(row.get("product_name") or row.get("product") or ""),
        sku=str(row.get("sku") or ""),
        variant=str(row.get("variant") or ""),
    )


def _planogram_identity(item: dict[str, Any]) -> str:
    return build_match_key(
        str(item.get("brand") or ""),
        str(item.get("product_name") or ""),
        sku=str(item.get("sku") or ""),
        variant=str(item.get("variant") or ""),
    )


def _token_overlap(a: str, b: str) -> float:
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _score_cv_to_planogram(cv: dict[str, Any], item: dict[str, Any]) -> float:
    cv_sku = _norm(cv.get("sku"))
    item_sku = _norm(item.get("sku"))
    if cv_sku and item_sku and cv_sku == item_sku:
        return 1.0
    if _cv_identity(cv) == _planogram_identity(item):
        return 0.95
    return _token_overlap(
        f"{cv.get('brand')} {cv.get('product_name')} {cv.get('variant')}",
        f"{item.get('brand')} {item.get('product_name')} {item.get('variant')}",
    )


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def join_planogram_with_cv(
    planogram_items: list[dict[str, Any]],
    cv_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build per-planogram-row joined records for shelf_calc."""
    used_cv: set[int] = set()
    rows: list[dict[str, Any]] = []

    for item in planogram_items:
        best_idx = -1
        best_score = 0.0
        for idx, cv in enumerate(cv_products):
            if idx in used_cv:
                continue
            score = _score_cv_to_planogram(cv, item)
            if score > best_score:
                best_score = score
                best_idx = idx

        expected_facings = _int_or_none(item.get("expected_facings") or item.get("expected_qty"))
        expected_units = _int_or_none(item.get("expected_shelf_units"))
        base = {
            "location": item.get("location"),
            "category": item.get("category"),
            "subcategory": item.get("sub_category") or item.get("subcategory"),
            "brand": item.get("brand"),
            "product_name": item.get("product_name"),
            "variant": item.get("variant"),
            "sku": item.get("sku"),
            "expected_facings": expected_facings,
            "min_facings": _int_or_none(item.get("min_facings")),
            "max_facings": _int_or_none(item.get("max_facings")),
            "expected_shelf_units": expected_units,
            "expected_mrp_inr": _float_or_none(item.get("mrp_inr")),
            "avg_daily_sales": _float_or_none(item.get("avg_daily_sales")),
            "expected_shelf_position": item.get("shelf_position"),
            "actual_shelf_position": None,
            "source_expected": "planogram",
        }

        if best_idx < 0 or best_score < _MATCH_THRESHOLD:
            rows.append(
                {
                    **base,
                    "actual_facings": None,
                    "actual_visible_units": None,
                    "match_status": "NOT_FOUND" if best_score < 0.3 else "UNVERIFIABLE",
                    "match_score": round(best_score, 3),
                    "source_actual": None,
                }
            )
            continue

        cv = cv_products[best_idx]
        used_cv.add(best_idx)
        rows.append(
            {
                **base,
                "actual_facings": _int_or_none(cv.get("actual_facings")),
                "actual_visible_units": _int_or_none(cv.get("actual_visible_units")),
                "match_status": "MATCHED",
                "match_score": round(best_score, 3),
                "confidence": cv.get("confidence"),
                "source_actual": "astra",
            }
        )

    return rows
