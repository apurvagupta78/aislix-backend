"""Canonical Aislix deterministic shelf/planogram calculation engine (v1)."""

from __future__ import annotations

import re
from typing import Any

from app.metric_result import (
    MetricResult,
    metric_result,
    not_applicable,
    percentage,
    unavailable,
    weighted_ratio,
)

FORMULA_VERSION = "v1"


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def normalize_brand(value: Any) -> str:
    return _norm(value)


def normalize_product_identity(brand: Any, product_name: Any, variant: Any = "", sku: Any = "") -> str:
    sku_key = _norm(sku)
    if sku_key:
        return f"sku:{sku_key}"
    return "|".join(
        filter(
            None,
            [
                normalize_brand(brand),
                _norm(product_name),
                _norm(variant),
            ],
        )
    )


def calculate_facing_variance(actual: int | None, expected: int | None) -> MetricResult:
    if actual is None or expected is None:
        return unavailable("facing_variance", unit="count")
    return metric_result(
        "facing_variance",
        value=int(actual) - int(expected),
        unit="count",
        inputs={"actual_facings": actual, "expected_facings": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_facing_variance_percent(actual: int | None, expected: int | None) -> MetricResult:
    if actual is None or expected is None:
        return unavailable("facing_variance_percent", unit="percent")
    if int(expected) == 0:
        return unavailable("facing_variance_percent", unit="percent", explanation="expected_facings is zero")
    variance = int(actual) - int(expected)
    pct = percentage(variance, expected)
    return metric_result(
        "facing_variance_percent",
        value=pct,
        unit="percent",
        inputs={"actual_facings": actual, "expected_facings": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_facing_compliance(actual: int | None, expected: int | None) -> MetricResult:
    if actual is None or expected is None:
        return unavailable("facing_compliance", unit="percent")
    if int(expected) == 0:
        return unavailable("facing_compliance", unit="percent", explanation="expected_facings is zero")
    pct = percentage(actual, expected)
    return metric_result(
        "facing_compliance",
        value=pct,
        unit="percent",
        inputs={"actual_facings": actual, "expected_facings": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_facing_compliance_aggregate(rows: list[dict[str, Any]]) -> MetricResult:
    actual_sum = 0
    expected_sum = 0
    for row in rows:
        actual = row.get("actual_facings")
        expected = row.get("expected_facings")
        if actual is None or expected is None:
            continue
        actual_sum += int(actual)
        expected_sum += int(expected)
    if expected_sum == 0:
        return unavailable("overall_facing_compliance", unit="percent")
    pct = weighted_ratio(actual_sum, expected_sum)
    return metric_result(
        "overall_facing_compliance",
        value=pct,
        unit="percent",
        inputs={"sum_actual_facings": actual_sum, "sum_expected_facings": expected_sum},
        formula_version=FORMULA_VERSION,
    )


def calculate_min_max_facing_status(
    actual: int | None,
    min_facings: int | None,
    max_facings: int | None,
) -> str:
    if actual is None:
        return "UNVERIFIABLE"
    act = int(actual)
    has_min = min_facings is not None and str(min_facings) != ""
    has_max = max_facings is not None and str(max_facings) != ""
    if not has_min and not has_max:
        return "NO_RANGE"
    if has_min and has_max:
        mn, mx = int(min_facings), int(max_facings)
        if act < mn:
            return "BELOW_MIN"
        if act > mx:
            return "ABOVE_MAX"
        return "WITHIN_RANGE"
    if has_min:
        return "MEETS_MIN" if act >= int(min_facings) else "BELOW_MIN"
    if has_max:
        return "WITHIN_MAX" if act <= int(max_facings) else "ABOVE_MAX"
    return "NO_RANGE"


def calculate_shelf_unit_variance(actual: int | None, expected: int | None) -> MetricResult:
    if actual is None or expected is None:
        return unavailable("shelf_unit_variance", unit="count")
    return metric_result(
        "shelf_unit_variance",
        value=int(actual) - int(expected),
        unit="count",
        inputs={"actual_visible_units": actual, "expected_shelf_units": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_shelf_unit_compliance(actual: int | None, expected: int | None) -> MetricResult:
    if actual is None or expected is None:
        return unavailable("shelf_unit_compliance", unit="percent")
    if int(expected) == 0:
        return unavailable("shelf_unit_compliance", unit="percent")
    pct = percentage(actual, expected)
    return metric_result(
        "shelf_unit_compliance",
        value=pct,
        unit="percent",
        inputs={"actual_visible_units": actual, "expected_shelf_units": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_visible_unit_shortfall(actual: int | None, expected: int | None) -> MetricResult:
    if expected is None:
        return unavailable("visible_unit_shortfall", unit="count")
    act = int(actual or 0)
    return metric_result(
        "visible_unit_shortfall",
        value=max(int(expected) - act, 0),
        unit="count",
        inputs={"actual_visible_units": act, "expected_shelf_units": expected},
        formula_version=FORMULA_VERSION,
    )


def calculate_visible_unit_value_gap(shortfall: int | None, mrp_inr: float | None) -> MetricResult:
    if shortfall is None or mrp_inr is None:
        return unavailable("potential_visible_unit_value_gap", unit="currency")
    return metric_result(
        "potential_visible_unit_value_gap",
        value=round(max(int(shortfall), 0) * float(mrp_inr), 2),
        unit="currency",
        inputs={"visible_unit_shortfall": shortfall, "mrp_inr": mrp_inr},
        formula_version=FORMULA_VERSION,
    )


def calculate_visible_shelf_coverage_days(actual: int | None, avg_daily_sales: float | None) -> MetricResult:
    if actual is None:
        return unavailable("estimated_visible_shelf_coverage_days", unit="days")
    if avg_daily_sales is None or float(avg_daily_sales) <= 0:
        return unavailable("estimated_visible_shelf_coverage_days", unit="days", explanation="avg_daily_sales unavailable")
    days = round(int(actual) / float(avg_daily_sales), 1)
    return metric_result(
        "estimated_visible_shelf_coverage_days",
        value=days,
        unit="days",
        inputs={"actual_visible_units": actual, "avg_daily_sales": avg_daily_sales},
        formula_version=FORMULA_VERSION,
    )


def calculate_brand_share(facings: int, total: int | None, *, metric_id: str = "brand_share_facings") -> MetricResult:
    if total is None or int(total) == 0:
        return unavailable(metric_id, unit="percent")
    pct = percentage(facings, total)
    return metric_result(
        metric_id,
        value=pct,
        unit="percent",
        inputs={"brand_facings": facings, "total_facings": total},
        formula_version=FORMULA_VERSION,
    )


def calculate_brand_share_variance_pp(actual_share: float | None, expected_share: float | None) -> MetricResult:
    if actual_share is None or expected_share is None:
        return unavailable("brand_share_variance_pp", unit="percentage_points")
    return metric_result(
        "brand_share_variance_pp",
        value=round(float(actual_share) - float(expected_share), 1),
        unit="percentage_points",
        inputs={"actual_share_percent": actual_share, "expected_share_percent": expected_share},
        formula_version=FORMULA_VERSION,
    )


def _row_checks(row: dict[str, Any]) -> tuple[int, int]:
    """Return (passed, applicable) check counts for planogram row."""
    passed = 0
    applicable = 0

    # presence
    match_status = str(row.get("match_status") or "").upper()
    if match_status in {"NOT_FOUND", "UNVERIFIABLE"}:
        applicable += 1
        if match_status == "NOT_FOUND":
            pass
        return passed, applicable

    applicable += 1
    passed += 1

    expected_facings = row.get("expected_facings")
    actual_facings = row.get("actual_facings")
    if expected_facings not in (None, "") and int(expected_facings or 0) > 0:
        applicable += 1
        if actual_facings is not None and int(actual_facings) >= int(expected_facings):
            passed += 1

    min_f = row.get("min_facings")
    max_f = row.get("max_facings")
    if min_f not in (None, "") or max_f not in (None, ""):
        applicable += 1
        status = calculate_min_max_facing_status(
            int(actual_facings) if actual_facings is not None else None,
            int(min_f) if min_f not in (None, "") else None,
            int(max_f) if max_f not in (None, "") else None,
        )
        if status in {"WITHIN_RANGE", "MEETS_MIN", "WITHIN_MAX", "NO_RANGE"}:
            passed += 1

    expected_units = row.get("expected_shelf_units")
    actual_units = row.get("actual_visible_units")
    if expected_units not in (None, "") and int(expected_units or 0) > 0:
        applicable += 1
        if actual_units is not None and int(actual_units) >= int(expected_units):
            passed += 1

    return passed, applicable


def calculate_planogram_compliance(rows: list[dict[str, Any]]) -> MetricResult:
    total_passed = 0
    total_applicable = 0
    for row in rows:
        passed, applicable = _row_checks(row)
        total_passed += passed
        total_applicable += applicable
    if total_applicable == 0:
        return unavailable("planogram_compliance", unit="percent")
    pct = weighted_ratio(total_passed, total_applicable)
    return metric_result(
        "planogram_compliance",
        value=pct,
        unit="percent",
        inputs={"passed_checks": total_passed, "applicable_checks": total_applicable},
        formula_version=FORMULA_VERSION,
    )


def build_planogram_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    actual_f = row.get("actual_facings")
    expected_f = row.get("expected_facings")
    actual_u = row.get("actual_visible_units")
    expected_u = row.get("expected_shelf_units")
    mrp = row.get("expected_mrp_inr") or row.get("mrp_inr")
    ads = row.get("avg_daily_sales")
    shortfall = calculate_visible_unit_shortfall(
        int(actual_u) if actual_u is not None else None,
        int(expected_u) if expected_u not in (None, "") else None,
    )
    shortfall_val = shortfall.value if shortfall.status == "CALCULATED" else None
    return {
        **row,
        "facing_variance": calculate_facing_variance(
            int(actual_f) if actual_f is not None else None,
            int(expected_f) if expected_f not in (None, "") else None,
        ).to_dict(),
        "facing_compliance": calculate_facing_compliance(
            int(actual_f) if actual_f is not None else None,
            int(expected_f) if expected_f not in (None, "") else None,
        ).to_dict(),
        "shelf_unit_compliance": calculate_shelf_unit_compliance(
            int(actual_u) if actual_u is not None else None,
            int(expected_u) if expected_u not in (None, "") else None,
        ).to_dict(),
        "visible_unit_shortfall": shortfall.to_dict(),
        "potential_visible_unit_value_gap": calculate_visible_unit_value_gap(
            int(shortfall_val) if shortfall_val is not None else None,
            float(mrp) if mrp not in (None, "") else None,
        ).to_dict(),
        "estimated_visible_shelf_coverage_days": calculate_visible_shelf_coverage_days(
            int(actual_u) if actual_u is not None else None,
            float(ads) if ads not in (None, "") else None,
        ).to_dict(),
        "min_max_facing_status": calculate_min_max_facing_status(
            int(actual_f) if actual_f is not None else None,
            int(row.get("min_facings")) if row.get("min_facings") not in (None, "") else None,
            int(row.get("max_facings")) if row.get("max_facings") not in (None, "") else None,
        ),
    }


def build_shelf_only_analysis(
    products: list[dict[str, Any]],
    *,
    count_validation: dict[str, Any],
) -> dict[str, Any]:
    facings_check = count_validation.get("total_actual_facings") or {}
    units_check = count_validation.get("total_actual_visible_units") or {}
    verified_facings = facings_check.get("verified_value")
    verified_units = units_check.get("verified_value")

    identities = {
        normalize_product_identity(p.get("brand"), p.get("product_name"), p.get("variant"), p.get("sku"))
        for p in products
        if str(p.get("product_status") or "IDENTIFIED").upper() != "UNVERIFIABLE"
    }
    brands = {
        normalize_brand(p.get("brand"))
        for p in products
        if p.get("brand") and str(p.get("brand_status") or "IDENTIFIED").upper() != "UNVERIFIABLE"
    }

    brand_facings: dict[str, int] = {}
    for p in products:
        brand = normalize_brand(p.get("brand"))
        if not brand:
            continue
        try:
            brand_facings[brand] = brand_facings.get(brand, 0) + int(p.get("actual_facings") or 0)
        except (TypeError, ValueError):
            continue

    total_facings_metric = (
        metric_result(
            "total_actual_facings",
            value=verified_facings,
            unit="count",
            source="astra",
            status="CALCULATED",
        )
        if facings_check.get("status") == "VERIFIED"
        else metric_result(
            "total_actual_facings",
            value=None,
            unit="count",
            status=facings_check.get("status", "UNAVAILABLE"),
            source="astra",
        )
    )

    brand_shares = []
    if verified_facings is not None and int(verified_facings) > 0:
        for brand, facings in sorted(brand_facings.items(), key=lambda item: (-item[1], item[0])):
            brand_shares.append(
                {
                    "brand": brand,
                    "actual_facings": facings,
                    "share": calculate_brand_share(facings, int(verified_facings)).to_dict(),
                }
            )

    calculated_metrics = {
        "products_identified": metric_result(
            "products_identified",
            value=len([i for i in identities if i]),
            unit="count",
        ).to_dict(),
        "brands_identified": metric_result(
            "brands_identified",
            value=len([b for b in brands if b]),
            unit="count",
        ).to_dict(),
        "total_actual_facings": total_facings_metric.to_dict(),
        "total_actual_visible_units": (
            metric_result(
                "total_actual_visible_units",
                value=verified_units,
                unit="count",
                source="astra",
            ).to_dict()
            if units_check.get("status") == "VERIFIED"
            else metric_result(
                "total_actual_visible_units",
                value=None,
                unit="count",
                status=units_check.get("status", "UNAVAILABLE"),
                source="astra",
            ).to_dict()
        ),
    }

    return {
        "mode": "shelf_only",
        "products": products,
        "brand_analysis": brand_shares,
        "calculated_metrics": calculated_metrics,
        "count_validation": count_validation,
    }


def build_planogram_analysis(
    rows: list[dict[str, Any]],
    *,
    count_validation: dict[str, Any],
    sku_match_percent: float | None = None,
) -> dict[str, Any]:
    enriched_rows = [build_planogram_row_metrics(row) for row in rows]
    planogram_compliance = calculate_planogram_compliance(enriched_rows)
    overall_facing = calculate_facing_compliance_aggregate(enriched_rows)

    calculated_metrics = {
        "planogram_compliance": planogram_compliance.to_dict(),
        "overall_facing_compliance": overall_facing.to_dict(),
    }
    if sku_match_percent is not None:
        calculated_metrics["planogram_sku_match_percent"] = metric_result(
            "planogram_sku_match_percent",
            value=round(float(sku_match_percent), 1),
            unit="percent",
            source="aislix_calculation",
        ).to_dict()

    facings_check = count_validation.get("total_actual_facings") or {}
    if facings_check.get("status") == "VERIFIED":
        calculated_metrics["total_actual_facings"] = metric_result(
            "total_actual_facings",
            value=facings_check.get("verified_value"),
            unit="count",
            source="astra",
        ).to_dict()

    return {
        "mode": "planogram",
        "products": enriched_rows,
        "calculated_metrics": calculated_metrics,
        "count_validation": count_validation,
    }
