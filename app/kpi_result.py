"""Typed KPI result contract — deterministic scoring separate from AI observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


RESULT_STATUSES = frozenset(
    {
        "complete",
        "partial",
        "not_assessable",
        "not_applicable",
        "not_configured",
    }
)

EVIDENCE_STATES = frozenset({"pass", "fail", "not_assessable", "needs_review"})


@dataclass
class KpiResult:
    kpi_id: str
    label: str
    value: float | int | None
    unit: str = "percent"
    status: str = "not_configured"
    numerator: float | int | None = None
    denominator: float | int | None = None
    coverage_percent: float | None = None
    coverage_numerator: int | None = None
    coverage_denominator: int | None = None
    excluded_count: int = 0
    formula: str = ""
    formula_version: str = "audit-kpi-v1"
    scope: str = ""
    warnings: list[str] = field(default_factory=list)
    tooltip: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        if out["value"] is not None and isinstance(out["value"], float):
            if out["value"] != out["value"]:  # NaN guard
                out["value"] = None
                out["status"] = "not_assessable"
        return out


def percent_or_none(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator) * 100.0, 4)


def finalize_percent_kpi(
    *,
    kpi_id: str,
    label: str,
    numerator: int,
    denominator: int,
    eligible_total: int | None = None,
    scope: str = "",
    formula: str = "",
    tooltip: str = "",
    warnings: list[str] | None = None,
) -> KpiResult:
    """Build a percentage KPI with assessment coverage metadata."""
    warnings = warnings or []
    if eligible_total is None:
        eligible_total = denominator

    if eligible_total <= 0:
        return KpiResult(
            kpi_id=kpi_id,
            label=label,
            value=None,
            unit="percent",
            status="not_applicable",
            numerator=0,
            denominator=0,
            coverage_percent=None,
            coverage_numerator=0,
            coverage_denominator=0,
            excluded_count=0,
            formula=formula,
            scope=scope,
            tooltip=tooltip,
            warnings=warnings,
        )

    if denominator <= 0:
        return KpiResult(
            kpi_id=kpi_id,
            label=label,
            value=None,
            unit="percent",
            status="not_assessable",
            numerator=0,
            denominator=0,
            coverage_percent=percent_or_none(0, eligible_total),
            coverage_numerator=0,
            coverage_denominator=eligible_total,
            excluded_count=eligible_total,
            formula=formula,
            scope=scope,
            tooltip=tooltip,
            warnings=warnings + ["No eligible units could be assessed."],
        )

    value = percent_or_none(numerator, denominator)
    coverage = percent_or_none(denominator, eligible_total)
    excluded = max(0, eligible_total - denominator)
    status = "complete" if denominator >= eligible_total else "partial"

    return KpiResult(
        kpi_id=kpi_id,
        label=label,
        value=value,
        unit="percent",
        status=status,
        numerator=numerator,
        denominator=denominator,
        coverage_percent=coverage,
        coverage_numerator=denominator,
        coverage_denominator=eligible_total,
        excluded_count=excluded,
        formula=formula,
        scope=scope,
        tooltip=tooltip,
        warnings=warnings,
    )
