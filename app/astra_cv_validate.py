"""Validate Astra shelf_cv JSON — count consistency and field sanity."""

from __future__ import annotations

import re
from typing import Any

SHELF_CV_TYPE = "shelf_cv"
VERIFIED = "VERIFIED"
COUNT_MISMATCH = "COUNT_MISMATCH"


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def is_shelf_cv_payload(data: dict[str, Any]) -> bool:
    analysis_type = _norm(data.get("analysis_type"))
    if analysis_type == SHELF_CV_TYPE:
        return True
    mode = _norm(data.get("analysis_mode"))
    return mode in {"no_planogram", "with_planogram", "shelf_only", "planogram_comparison", "image_only_shelf_analysis"}


def _row_countable(row: dict[str, Any], field_name: str) -> bool:
    status_key = {
        "actual_facings": None,
        "actual_visible_units": None,
    }.get(field_name)
    value = row.get(field_name)
    if value is None:
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def sum_product_field(products: list[dict[str, Any]], field_name: str) -> int | None:
    if not products:
        return 0
    total = 0
    any_countable = False
    for row in products:
        if not isinstance(row, dict):
            continue
        if not _row_countable(row, field_name):
            continue
        any_countable = True
        total += max(0, int(row.get(field_name) or 0))
    return total if any_countable else None


def verify_count_field(
    products: list[dict[str, Any]],
    summary: dict[str, Any],
    field_name: str,
    summary_key: str,
) -> dict[str, Any]:
    product_sum = sum_product_field(products, field_name)
    summary_raw = summary.get(summary_key)
    try:
        astra_summary = int(summary_raw) if summary_raw is not None else None
    except (TypeError, ValueError):
        astra_summary = None

    if product_sum is None and astra_summary is None:
        return {
            "field": field_name,
            "status": "UNAVAILABLE",
            "product_sum": None,
            "astra_summary": None,
            "verified_value": None,
        }

    if product_sum is None or astra_summary is None:
        return {
            "field": field_name,
            "status": COUNT_MISMATCH,
            "product_sum": product_sum,
            "astra_summary": astra_summary,
            "verified_value": None,
        }

    if product_sum != astra_summary:
        return {
            "field": field_name,
            "status": COUNT_MISMATCH,
            "product_sum": product_sum,
            "astra_summary": astra_summary,
            "verified_value": None,
        }

    return {
        "field": field_name,
        "status": VERIFIED,
        "product_sum": product_sum,
        "astra_summary": astra_summary,
        "verified_value": product_sum,
    }


def verify_astra_count_consistency(data: dict[str, Any]) -> dict[str, Any]:
    """Compare product-level sums vs Astra summary totals."""
    products = [row for row in (data.get("products") or []) if isinstance(row, dict)]
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}

    facings = verify_count_field(products, summary, "actual_facings", "total_actual_facings")
    units = verify_count_field(products, summary, "actual_visible_units", "total_actual_visible_units")

    has_mismatch = any(row.get("status") == COUNT_MISMATCH for row in (facings, units))
    all_verified = all(row.get("status") == VERIFIED for row in (facings, units) if row.get("status") != "UNAVAILABLE")

    return {
        "total_actual_facings": facings,
        "total_actual_visible_units": units,
        "count_verification_status": COUNT_MISMATCH if has_mismatch else (VERIFIED if all_verified else "PARTIAL"),
        "scan_complete": not has_mismatch,
    }
