"""Canonical MetricResult contract for Aislix deterministic calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

MetricStatus = Literal[
    "CALCULATED",
    "UNAVAILABLE",
    "UNVERIFIABLE",
    "NOT_APPLICABLE",
    "COUNT_MISMATCH",
]

MetricSource = Literal[
    "aislix_calculation",
    "astra",
    "luna",
    "planogram",
    "master_data",
    "user_input",
    "database",
]

MetricUnit = Literal["percent", "count", "currency", "days", "percentage_points", "ratio", "text"]


@dataclass
class MetricResult:
    metric_id: str
    value: float | int | str | None
    unit: MetricUnit
    status: MetricStatus
    source: MetricSource
    formula_version: str = "v1"
    inputs: dict[str, Any] = field(default_factory=dict)
    calculated_at: str = ""
    explanation: str | None = None

    def __post_init__(self) -> None:
        if not self.calculated_at:
            self.calculated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    try:
        den = float(denominator)
        if den == 0:
            return None
        return float(numerator) / den
    except (TypeError, ValueError):
        return None


def percentage(
    numerator: float | int | None,
    denominator: float | int | None,
    *,
    decimals: int = 1,
) -> float | None:
    ratio = safe_divide(numerator, denominator)
    if ratio is None:
        return None
    return round(ratio * 100.0, decimals)


def weighted_ratio(
    sum_numerator: float | int | None,
    sum_denominator: float | int | None,
    *,
    decimals: int = 1,
) -> float | None:
    return percentage(sum_numerator, sum_denominator, decimals=decimals)


def metric_result(
    metric_id: str,
    *,
    value: float | int | str | None,
    unit: MetricUnit,
    status: MetricStatus = "CALCULATED",
    source: MetricSource = "aislix_calculation",
    formula_version: str = "v1",
    inputs: dict[str, Any] | None = None,
    explanation: str | None = None,
) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        value=value,
        unit=unit,
        status=status,
        source=source,
        formula_version=formula_version,
        inputs=inputs or {},
        explanation=explanation,
    )


def unavailable(metric_id: str, *, unit: MetricUnit = "percent", reason: str | None = None) -> MetricResult:
    return metric_result(
        metric_id,
        value=None,
        unit=unit,
        status="UNAVAILABLE",
        explanation=reason,
    )


def not_applicable(metric_id: str, *, unit: MetricUnit = "percent", reason: str | None = None) -> MetricResult:
    return metric_result(
        metric_id,
        value=None,
        unit=unit,
        status="NOT_APPLICABLE",
        explanation=reason,
    )
