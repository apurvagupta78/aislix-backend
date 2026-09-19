"""Rule-based execution risk scoring — no LLM."""

from __future__ import annotations

from typing import Any

from app.risk_rules_config import DEFAULT_RISK_THRESHOLDS, RiskThresholds

SEVERITY_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _max_severity(current: str, candidate: str) -> str:
    return candidate if SEVERITY_ORDER.get(candidate, 0) > SEVERITY_ORDER.get(current, 0) else current


def evaluate_execution_risk(
    *,
    count_validation: dict[str, Any] | None,
    calculated_metrics: dict[str, Any] | None,
    planogram_rows: list[dict[str, Any]] | None = None,
    thresholds: RiskThresholds = DEFAULT_RISK_THRESHOLDS,
) -> dict[str, Any]:
    """Return deterministic execution risk payload."""
    severity = "NONE"
    rules_triggered: list[dict[str, Any]] = []
    reasons: list[str] = []

    count_validation = count_validation or {}
    calculated_metrics = calculated_metrics or {}
    planogram_rows = planogram_rows or []

    if count_validation.get("count_verification_status") == "COUNT_MISMATCH":
        if thresholds.count_mismatch_critical:
            severity = _max_severity(severity, "CRITICAL")
            rules_triggered.append(
                {
                    "rule_id": "count_mismatch",
                    "severity": "CRITICAL",
                    "description": "Visual count verification pending review.",
                }
            )
            reasons.append("Visual count totals disagree between product rows and Astra summary.")

    not_found = sum(1 for row in planogram_rows if str(row.get("match_status") or "").upper() == "NOT_FOUND")
    if not_found >= thresholds.not_found_row_high:
        severity = _max_severity(severity, "HIGH")
        rules_triggered.append(
            {
                "rule_id": "planogram_not_found",
                "severity": "HIGH",
                "description": f"{not_found} expected planogram rows not found on shelf.",
            }
        )
        reasons.append(f"{not_found} planogram rows marked NOT_FOUND.")

    for row in planogram_rows:
        status = str(row.get("min_max_facing_status") or "").upper()
        if status == "BELOW_MIN" and thresholds.facing_below_min_high:
            severity = _max_severity(severity, "HIGH")
            rules_triggered.append(
                {
                    "rule_id": "below_min_facings",
                    "severity": "HIGH",
                    "description": "Product below minimum facing requirement.",
                    "product": row.get("product_name"),
                    "brand": row.get("brand"),
                }
            )
            reasons.append(f"Below min facings: {row.get('brand')} {row.get('product_name')}.")
            break

        expected_units = row.get("expected_shelf_units")
        actual_units = row.get("actual_visible_units")
        if expected_units not in (None, "") and int(expected_units or 0) > 0:
            act = int(actual_units or 0)
            if act == 0:
                severity = _max_severity(severity, "CRITICAL")
                rules_triggered.append(
                    {
                        "rule_id": "expected_units_zero_actual",
                        "severity": "CRITICAL",
                        "description": "Expected shelf units present in planogram but zero visible units detected.",
                        "product": row.get("product_name"),
                    }
                )
                reasons.append(f"Zero visible units for expected SKU: {row.get('product_name')}.")
            elif int(expected_units) - act >= thresholds.shortfall_units_high:
                severity = _max_severity(severity, "MEDIUM")
                rules_triggered.append(
                    {
                        "rule_id": "visible_unit_shortfall",
                        "severity": "MEDIUM",
                        "description": "Material visible unit shortfall versus planogram expectation.",
                        "product": row.get("product_name"),
                    }
                )

        coverage = row.get("estimated_visible_shelf_coverage_days")
        if isinstance(coverage, dict):
            cov_val = coverage.get("value")
            cov_status = coverage.get("status")
            if cov_status == "CALCULATED" and cov_val is not None:
                days = float(cov_val)
                if days <= thresholds.coverage_days_critical:
                    severity = _max_severity(severity, "CRITICAL")
                    rules_triggered.append(
                        {
                            "rule_id": "coverage_critical",
                            "severity": "CRITICAL",
                            "description": "Estimated visible shelf coverage below critical threshold.",
                        }
                    )
                elif days <= thresholds.coverage_days_high:
                    severity = _max_severity(severity, "HIGH")
                    rules_triggered.append(
                        {
                            "rule_id": "coverage_high",
                            "severity": "HIGH",
                            "description": "Estimated visible shelf coverage below high-risk threshold.",
                        }
                    )

    plano = calculated_metrics.get("planogram_compliance")
    if isinstance(plano, dict) and plano.get("status") == "CALCULATED":
        value = plano.get("value")
        if value is not None and float(value) < 70:
            severity = _max_severity(severity, "MEDIUM")
            rules_triggered.append(
                {
                    "rule_id": "planogram_compliance_low",
                    "severity": "MEDIUM",
                    "description": f"Check-based planogram compliance below 70% ({value}%).",
                }
            )

    return {
        "severity": severity,
        "rules_triggered": rules_triggered,
        "reasons": reasons,
    }
