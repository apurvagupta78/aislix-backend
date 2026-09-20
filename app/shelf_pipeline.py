"""Orchestrate Astra CV validation → Aislix calc → risk → executive summary."""

from __future__ import annotations

from typing import Any

from app.astra_cv_validate import is_shelf_cv_payload, verify_astra_count_consistency
from app.cv_brand_canonicalize import canonicalize_shelf_cv_products
from app.executive_summary_builder import build_executive_summary
from app.execution_risk import evaluate_execution_risk
from app.planogram_match import join_planogram_with_cv
from app.shelf_calc import FORMULA_VERSION, build_planogram_analysis, build_shelf_only_analysis

CALC_ENGINE_VERSION = "shelf_calc_v1"


def normalize_api_analysis_mode(metadata: dict[str, Any], astra_payload: dict[str, Any]) -> str:
    requested = str(metadata.get("analysis_mode") or "").strip().lower()
    if requested in {"planogram_comparison", "with_planogram"}:
        return "planogram_comparison"
    if requested in {"shelf_only", "no_planogram", "image_only_shelf_analysis"}:
        return "shelf_only"

    mode = str(astra_payload.get("analysis_mode") or "").strip().lower()
    if mode in {"with_planogram", "planogram_comparison"}:
        return "planogram_comparison"
    return "shelf_only"


def run_shelf_cv_pipeline(
    astra_payload: dict[str, Any],
    metadata: dict[str, Any],
    *,
    luna_analysis: dict[str, Any] | None = None,
    legacy_planogram_compliance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return shelf CV pipeline blocks to merge into scan metrics/result."""
    if not is_shelf_cv_payload(astra_payload):
        return None

    products = [row for row in (astra_payload.get("products") or []) if isinstance(row, dict)]
    canonicalize_shelf_cv_products(products)
    astra_payload["products"] = products
    count_validation = verify_astra_count_consistency(astra_payload)
    analysis_mode = normalize_api_analysis_mode(metadata, astra_payload)
    scan_complete = bool(count_validation.get("scan_complete"))

    sku_match_percent = None
    if legacy_planogram_compliance:
        sku_match_percent = legacy_planogram_compliance.get("planogram_sku_match_percent")

    if analysis_mode == "planogram_comparison":
        planogram_items = metadata.get("planogram_items") or []
        joined_rows = join_planogram_with_cv(planogram_items, products) if planogram_items else []
        aislix_analysis = build_planogram_analysis(
            joined_rows,
            count_validation=count_validation,
            sku_match_percent=sku_match_percent,
        )
        aislix_key = "aislix_planogram_analysis"
    else:
        aislix_analysis = build_shelf_only_analysis(products, count_validation=count_validation)
        aislix_key = "aislix_shelf_analysis"

    calculated_metrics = aislix_analysis.get("calculated_metrics") or {}
    if not scan_complete:
        for key in ("total_actual_facings", "total_actual_visible_units", "planogram_compliance", "overall_facing_compliance"):
            if key in calculated_metrics and isinstance(calculated_metrics[key], dict):
                calculated_metrics[key]["status"] = "COUNT_MISMATCH"
                calculated_metrics[key]["value"] = None

    execution_risk = evaluate_execution_risk(
        count_validation=count_validation,
        calculated_metrics=calculated_metrics,
        planogram_rows=aislix_analysis.get("products") if analysis_mode == "planogram_comparison" else None,
    )

    findings = metadata.get("findings") if isinstance(metadata.get("findings"), list) else []
    corrective_actions = metadata.get("corrective_actions") if isinstance(metadata.get("corrective_actions"), list) else []
    if legacy_planogram_compliance and isinstance(legacy_planogram_compliance.get("corrective_actions"), list):
        corrective_actions = legacy_planogram_compliance["corrective_actions"]

    summary_payload = build_executive_summary(
        metadata=metadata,
        analysis_mode=analysis_mode,
        astra_cv=astra_payload,
        count_validation=count_validation,
        calculated_metrics=calculated_metrics,
        aislix_analysis=aislix_analysis,
        execution_risk=execution_risk,
        luna_analysis=luna_analysis,
        findings=findings,
        corrective_actions=corrective_actions,
    )

    return {
        "analysis_mode": analysis_mode,
        "scan_complete": scan_complete,
        "scan_status": "needs_review" if not scan_complete else "complete",
        "calc_engine_version": CALC_ENGINE_VERSION,
        "formula_version": FORMULA_VERSION,
        "astra_cv_analysis": astra_payload,
        "astra_cv_validation": count_validation,
        aislix_key: aislix_analysis,
        "calculated_metrics": calculated_metrics,
        "execution_risk": execution_risk,
        "luna_secondary_analysis": luna_analysis,
        **summary_payload,
    }
