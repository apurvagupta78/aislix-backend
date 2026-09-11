"""Deterministic KPI calculators — formulas match shelf-audit specification."""

from __future__ import annotations

from typing import Any

from app.kpi_result import KpiResult, finalize_percent_kpi, percent_or_none


def compute_osa(
    *,
    listed_available: int,
    listed_assessed: int,
    listed_eligible: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="osa",
        label="On-Shelf Availability (OSA)",
        numerator=listed_available,
        denominator=listed_assessed,
        eligible_total=listed_eligible,
        scope=scope,
        formula="(Listed SKUs visibly available / Listed SKUs assessed) × 100",
        tooltip="Each eligible SKU counted once. Misplaced but visible SKUs count as available.",
    )


def compute_planogram_compliance(
    *,
    positions_passing: int,
    positions_assessed: int,
    positions_eligible: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="planogram_compliance",
        label="Planogram Compliance",
        numerator=positions_passing,
        denominator=positions_assessed,
        eligible_total=positions_eligible,
        scope=scope,
        formula="(Positions passing all required layout checks / Required positions assessed) × 100",
    )


def compute_assortment_compliance(
    *,
    present_required: int,
    assessed_required: int,
    eligible_required: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="assortment_compliance",
        label="Assortment Compliance",
        numerator=present_required,
        denominator=assessed_required,
        eligible_total=eligible_required,
        scope=scope,
        formula="(Required assortment SKUs visibly present / Required assortment SKUs assessed) × 100",
        tooltip="Uses mandatory assortment list only — optional SKUs excluded from denominator.",
    )


def compute_price_compliance(
    *,
    labels_passing: int,
    labels_assessed: int,
    labels_eligible: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="price_compliance",
        label="Price Compliance",
        numerator=labels_passing,
        denominator=labels_assessed,
        eligible_total=labels_eligible,
        scope=scope,
        formula="(Required price-label positions meeting approved requirements / Required positions assessed) × 100",
    )


def compute_promotional_compliance(
    *,
    promotions_passing: int,
    promotions_assessed: int,
    promotions_eligible: int,
    scope: str = "",
    active_promotions: int | None = None,
) -> KpiResult:
    if active_promotions is not None and active_promotions <= 0:
        return KpiResult(
            kpi_id="promotional_compliance",
            label="Promotional Compliance",
            value=None,
            unit="percent",
            status="not_applicable",
            numerator=0,
            denominator=0,
            coverage_percent=None,
            coverage_numerator=0,
            coverage_denominator=0,
            formula="(Active promotions passing all required visual checks / Active promotions assessed) × 100",
            scope=scope,
            tooltip="No active promotions at capture time.",
        )
    return finalize_percent_kpi(
        kpi_id="promotional_compliance",
        label="Promotional Compliance",
        numerator=promotions_passing,
        denominator=promotions_assessed,
        eligible_total=promotions_eligible,
        scope=scope,
        formula="(Active promotions passing all required visual checks / Active promotions assessed) × 100",
    )


def compute_location_accuracy(
    *,
    locations_correct: int,
    locations_assessed: int,
    locations_eligible: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="location_accuracy",
        label="Location Accuracy",
        numerator=locations_correct,
        denominator=locations_assessed,
        eligible_total=locations_eligible,
        scope=scope,
        formula="(Occupied locations containing only approved SKUs / Occupied locations assessed) × 100",
        tooltip="Empty locations excluded from denominator; handled by availability checks.",
    )


def compute_facing_count(
    *,
    actual_facings: int,
    planned_facings: int | None = None,
    positions_assessed: int = 0,
    positions_eligible: int = 0,
    scope: str = "",
    partial_coverage: bool = False,
) -> KpiResult:
    status = "complete"
    coverage = percent_or_none(positions_assessed, positions_eligible) if positions_eligible else None
    if partial_coverage or (positions_eligible and positions_assessed < positions_eligible):
        status = "partial"
    warnings: list[str] = []
    if partial_coverage:
        warnings.append("Observed partial count — fixture coverage incomplete.")

    return KpiResult(
        kpi_id="facing_count",
        label="Facing Count",
        value=actual_facings,
        unit="count",
        status=status if actual_facings is not None else "not_assessable",
        numerator=actual_facings,
        denominator=planned_facings,
        coverage_percent=coverage,
        coverage_numerator=positions_assessed or None,
        coverage_denominator=positions_eligible or None,
        excluded_count=max(0, (positions_eligible or 0) - (positions_assessed or 0)),
        formula="Sum of visible front facings for assessed SKUs",
        scope=scope,
        tooltip="Does not count hidden units behind the front row.",
        warnings=warnings,
    )


def compute_share_of_shelf(
    *,
    brand_linear_cm: float,
    total_linear_cm: float,
    scope: str = "",
    measurement_basis: str = "linear_shelf_length",
    calibrated: bool = True,
) -> KpiResult:
    if not calibrated or total_linear_cm <= 0:
        return KpiResult(
            kpi_id="share_of_shelf",
            label="Share of Shelf (SOS)",
            value=None,
            unit="percent",
            status="not_assessable",
            numerator=brand_linear_cm if brand_linear_cm else None,
            denominator=total_linear_cm if total_linear_cm else None,
            formula="(Brand occupied linear shelf space / Total occupied linear shelf space in category) × 100",
            scope=scope,
            tooltip="Requires category boundary and shelf geometry calibration.",
            warnings=["Insufficient calibration or category coverage for linear SOS."],
        )
    value = percent_or_none(brand_linear_cm, total_linear_cm)
    return KpiResult(
        kpi_id="share_of_shelf",
        label="Share of Shelf (SOS)",
        value=value,
        unit="percent",
        status="complete",
        numerator=round(brand_linear_cm, 4),
        denominator=round(total_linear_cm, 4),
        coverage_percent=100.0,
        formula="(Brand occupied linear shelf space / Total occupied linear shelf space in category) × 100",
        scope=scope,
        tooltip=f"Measurement basis: {measurement_basis}. Not market share.",
    )


def compute_msl_compliance(
    *,
    present_msl: int,
    assessed_msl: int,
    eligible_msl: int,
    scope: str = "",
) -> KpiResult:
    return finalize_percent_kpi(
        kpi_id="msl_compliance",
        label="Must-Stock List (MSL) Compliance",
        numerator=present_msl,
        denominator=assessed_msl,
        eligible_total=eligible_msl,
        scope=scope,
        formula="(Required MSL SKUs visibly present / Required MSL SKUs assessed) × 100",
        tooltip="Uses outlet-specific must-stock list valid at capture date.",
    )


def not_configured_kpi(kpi_id: str, label: str, *, scope: str = "", tooltip: str = "") -> KpiResult:
    return KpiResult(
        kpi_id=kpi_id,
        label=label,
        value=None,
        unit="percent" if kpi_id != "facing_count" else "count",
        status="not_configured",
        scope=scope,
        tooltip=tooltip or "Required reference data not supplied in planogram package.",
    )


def assess_units_from_states(units: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Return (pass_count, assessed_count, eligible_count) from unit evidence states."""
    eligible = len(units)
    assessed = sum(1 for u in units if u.get("state") != "not_assessable")
    passing = sum(1 for u in units if u.get("state") == "pass")
    return passing, assessed, eligible
