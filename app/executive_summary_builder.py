"""Deterministic 13-section executive summary — no LLM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _metric_value(metrics: dict[str, Any], key: str) -> tuple[Any, str]:
    block = metrics.get(key)
    if isinstance(block, dict):
        return block.get("value"), str(block.get("status") or "")
    return block, "CALCULATED" if block is not None else "UNAVAILABLE"


def _format_metric(metrics: dict[str, Any], key: str, suffix: str = "") -> str:
    value, status = _metric_value(metrics, key)
    if status == "COUNT_MISMATCH":
        return "Visual count verification pending review."
    if status in {"UNAVAILABLE", "UNVERIFIABLE", "NOT_APPLICABLE"} or value is None:
        return "Data unavailable"
    return f"{value}{suffix}"


def build_executive_summary(
    *,
    metadata: dict[str, Any],
    analysis_mode: str,
    astra_cv: dict[str, Any],
    count_validation: dict[str, Any],
    calculated_metrics: dict[str, Any],
    aislix_analysis: dict[str, Any] | None,
    execution_risk: dict[str, Any] | None,
    luna_analysis: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    corrective_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    image_quality = astra_cv.get("image_quality") if isinstance(astra_cv.get("image_quality"), dict) else {}
    iq_status = image_quality.get("status") or "Data unavailable"
    iq_reason = image_quality.get("reason") or "—"

    location = metadata.get("location") or metadata.get("shelf_label") or "Not supplied"
    category = metadata.get("category") or metadata.get("aislix_category") or "General"
    sub_category = metadata.get("sub_category") or "General"
    operating_model = astra_cv.get("operating_model") or metadata.get("operating_model") or "Not supplied"
    assignment = metadata.get("assignment_name") or metadata.get("audit_name") or "Ad hoc shelf audit"
    mode_display = "Planogram comparison" if analysis_mode == "planogram_comparison" else "Shelf-only"

    section1 = "\n".join(
        [
            f"Audit: {assignment} · {location} · {category}/{sub_category}",
            f"Operating model: {operating_model} · Mode: {mode_display}",
            f"Image quality: {iq_status} ({iq_reason})",
        ]
    )

    bullets: list[str] = []
    if count_validation.get("count_verification_status") == "COUNT_MISMATCH":
        bullets.append("Visual count verification pending review.")
    plano_val, plano_status = _metric_value(calculated_metrics, "planogram_compliance")
    if plano_status == "CALCULATED" and plano_val is not None:
        bullets.append(f"Planogram compliance: {plano_val}% (check-based).")
    elif analysis_mode == "planogram_comparison":
        bullets.append("Planogram compliance: Data unavailable")
    risk = execution_risk or {}
    if risk.get("severity") and risk.get("severity") != "NONE":
        bullets.append(f"Overall execution risk: {risk.get('severity')}.")
    if not bullets:
        bullets.append("Shelf audit completed with available visual evidence.")
    section2 = "\n".join(f"- {b}" for b in bullets[:5])

    section3_lines = [
        f"Products identified: {_format_metric(calculated_metrics, 'products_identified')}",
        f"Brands identified: {_format_metric(calculated_metrics, 'brands_identified')}",
        f"Total actual facings: {_format_metric(calculated_metrics, 'total_actual_facings')}",
        f"Total actual visible units: {_format_metric(calculated_metrics, 'total_actual_visible_units')}",
        f"Overall facing compliance: {_format_metric(calculated_metrics, 'overall_facing_compliance', '%')}",
    ]
    section3 = "\n".join(section3_lines)

    if analysis_mode != "planogram_comparison":
        section4 = "Not applicable — no planogram expected state."
    else:
        sku_match = _format_metric(calculated_metrics, "planogram_sku_match_percent", "%")
        section4 = "\n".join(
            [
                f"Check-based planogram compliance: {_format_metric(calculated_metrics, 'planogram_compliance', '%')}",
                f"SKU match percent: {sku_match}",
            ]
        )

    section5_lines: list[str] = []
    rows = (aislix_analysis or {}).get("products") or []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        fc = row.get("facing_compliance")
        fc_val = fc.get("value") if isinstance(fc, dict) else None
        fc_status = fc.get("status") if isinstance(fc, dict) else "UNAVAILABLE"
        compliance_text = (
            f"{fc_val}%"
            if fc_status == "CALCULATED" and fc_val is not None
            else "Verification required"
        )
        section5_lines.append(
            f"{row.get('brand')} {row.get('product_name')} {row.get('variant') or ''}: "
            f"facings {row.get('actual_facings')}/{row.get('expected_facings')}, compliance {compliance_text}"
        )
    section5 = "\n".join(section5_lines) if section5_lines else "Data unavailable"

    section6 = "Brand share metrics available in calculated analysis." if calculated_metrics else "Data unavailable"

    if luna_analysis:
        prices = luna_analysis.get("visible_prices") or []
        promos = luna_analysis.get("promotions") or []
        section7 = f"Price observations: {len(prices)} · Promotions: {len(promos)}"
    else:
        section7 = "Price and promotion intelligence: Data unavailable."

    shelf_issues = (luna_analysis or {}).get("shelf_issues") or []
    section8 = (
        "\n".join(f"- {issue}" if isinstance(issue, str) else f"- {issue.get('description')}" for issue in shelf_issues[:5])
        if shelf_issues
        else "No shelf execution issues recorded."
    )

    section9 = f"Overall execution risk: {risk.get('severity', 'NONE')}."
    if risk.get("rules_triggered"):
        section9 += "\n" + "\n".join(
            f"- {rule.get('description')}" for rule in risk.get("rules_triggered", [])[:5]
        )

    findings = findings or []
    corrective_actions = corrective_actions or []
    if findings or corrective_actions:
        section10 = (
            f"Findings: {len(findings)} · Corrective actions: {len(corrective_actions)} "
            f"({sum(1 for a in corrective_actions if str(a.get('status') or '').lower() == 'open')} open)"
        )
    else:
        section10 = "No structured findings or corrective actions recorded."

    section11 = "Evidence: original image, annotated overlay, PDF report attached."

    next_actions: list[str] = []
    if count_validation.get("count_verification_status") == "COUNT_MISMATCH":
        next_actions.append("Reprocess scan or manually verify visual counts (count mismatch detected).")
    for rule in (risk.get("rules_triggered") or [])[:3]:
        if rule.get("severity") in {"CRITICAL", "HIGH"}:
            next_actions.append(str(rule.get("description")))
    section12 = (
        "\n".join(f"- {a}" for a in next_actions[:5])
        if next_actions
        else "No automated next actions — review detailed appendix."
    )

    appendix_lines: list[str] = []
    products = (aislix_analysis or {}).get("products") or astra_cv.get("products") or []
    for row in products[:20]:
        if not isinstance(row, dict):
            continue
        appendix_lines.append(
            f"{row.get('brand')} | {row.get('product_name')} | facings {row.get('actual_facings')} | "
            f"units {row.get('actual_visible_units')}"
        )
    section13 = "\n".join(appendix_lines) if appendix_lines else "Data unavailable"

    sections = {
        "audit_overview": section1,
        "executive_findings": section2,
        "overall_kpi_summary": section3,
        "planogram_compliance": section4,
        "product_sku_performance": section5,
        "brand_category_performance": section6,
        "price_promotion_intelligence": section7,
        "shelf_execution_issues": section8,
        "risk_priority": section9,
        "findings_corrective_actions": section10,
        "evidence_summary": section11,
        "recommended_next_actions": section12,
        "product_appendix": section13,
    }

    full_text = "\n\n".join(
        [
            "## Audit Overview",
            section1,
            "## Executive Findings",
            section2,
            "## Overall KPI Summary",
            section3,
            "## Planogram Compliance",
            section4,
            "## Product / SKU Performance",
            section5,
            "## Brand & Category Performance",
            section6,
            "## Price & Promotion Intelligence",
            section7,
            "## Shelf / Execution Issues",
            section8,
            "## Risk & Priority",
            section9,
            "## Findings & Corrective Actions",
            section10,
            "## Evidence Summary",
            section11,
            "## Recommended Next Actions",
            section12,
            "## Detailed Product Appendix",
            section13,
        ]
    )

    return {
        "executive_summary": full_text,
        "executive_summary_sections": sections,
        "executive_summary_meta": {
            "generator": "aislix_deterministic_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": [
                "calculated_metrics",
                "astra_cv_validation",
                "execution_risk",
                *(["luna_secondary_analysis"] if luna_analysis else []),
            ],
        },
    }
