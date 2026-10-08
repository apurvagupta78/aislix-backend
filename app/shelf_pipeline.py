"""Orchestrate Astra CV validation → Aislix calc → risk → executive summary."""

from __future__ import annotations

from typing import Any

from app.astra_cv_validate import (
    apply_visible_units_cap,
    cap_visible_units_to_facings,
    is_shelf_cv_payload,
    verify_astra_count_consistency,
)
from app.cv_brand_canonicalize import canonicalize_shelf_cv_products
from app.executive_summary_builder import build_executive_summary
from app.location_analysis import annotate_planogram_rows, build_location_analysis
from app.metric_result import not_applicable
from app.execution_risk import evaluate_execution_risk
from app.planogram_match import join_planogram_with_cv
from app.reference_match import build_reference_match, is_reference_comparison
from app.shelf_calc import (
    FORMULA_VERSION,
    build_planogram_analysis,
    build_shelf_only_analysis,
    enrich_financial_impact_with_inventory,
)

CALC_ENGINE_VERSION = "shelf_calc_v1"

_IDENTIFICATION_METRICS = (
    "products_identified",
    "brands_identified",
    "variants_identified",
    "total_actual_visible_units",
)
_PRESENCE_ONLY_REASON = "Your document has no facing targets — each line is checked for presence."


def _add_identification_metrics(
    aislix_analysis: dict[str, Any],
    products: list[dict[str, Any]],
    count_validation: dict[str, Any],
) -> None:
    """Planogram scans report what the AI identified on the shelf, same as shelf-only scans."""
    shelf_metrics = build_shelf_only_analysis(products, count_validation=count_validation)["calculated_metrics"]
    calculated = aislix_analysis.setdefault("calculated_metrics", {})
    for key in _IDENTIFICATION_METRICS:
        if key not in calculated and key in shelf_metrics:
            calculated[key] = shelf_metrics[key]


def document_sets_facings(metadata: dict[str, Any]) -> bool:
    """True when the reference document carries facing targets (a planogram or a facings column)."""
    document = metadata.get("reference_document")
    document = document if isinstance(document, dict) else {}
    if str(document.get("document_type") or "").strip().lower() == "planogram":
        return True
    if any("facing" in str(header).lower() for header in document.get("extra_columns") or []):
        return True
    for item in metadata.get("planogram_items") or []:
        if not isinstance(item, dict):
            continue
        try:
            if int(float(item.get("expected_facings") or 0)) > 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def mark_facings_not_applicable(aislix_analysis: dict[str, Any]) -> None:
    """Invoices / stock lists only expect presence, so facing compliance has no target."""
    calculated = aislix_analysis.setdefault("calculated_metrics", {})
    calculated["overall_facing_compliance"] = not_applicable(
        "overall_facing_compliance", reason=_PRESENCE_ONLY_REASON
    ).to_dict()
    for row in aislix_analysis.get("products") or []:
        if not isinstance(row, dict):
            continue
        row["facing_compliance"] = not_applicable("facing_compliance", reason=_PRESENCE_ONLY_REASON).to_dict()
        row["facing_variance"] = not_applicable(
            "facing_variance", unit="count", reason=_PRESENCE_ONLY_REASON
        ).to_dict()
    aislix_analysis["facing_targets"] = False


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
    apply_visible_units_cap(count_validation, products, cap_visible_units_to_facings(products))
    analysis_mode = normalize_api_analysis_mode(metadata, astra_payload)
    scan_complete = bool(count_validation.get("scan_complete"))

    location_analysis = build_location_analysis(products, astra_payload)

    sku_match_percent = None
    if legacy_planogram_compliance:
        sku_match_percent = legacy_planogram_compliance.get("planogram_sku_match_percent")

    if analysis_mode == "planogram_comparison":
        planogram_items = metadata.get("planogram_items") or []
        if planogram_items:
            joined_rows, unplanned = join_planogram_with_cv(planogram_items, products)
            annotate_planogram_rows(joined_rows, location_analysis)
        else:
            joined_rows, unplanned = [], []
        aislix_analysis = build_planogram_analysis(
            joined_rows,
            count_validation=count_validation,
            sku_match_percent=sku_match_percent,
            unplanned_products=unplanned,
        )
        _add_identification_metrics(aislix_analysis, products, count_validation)
        if is_reference_comparison(metadata) and not document_sets_facings(metadata):
            mark_facings_not_applicable(aislix_analysis)
        aislix_key = "aislix_planogram_analysis"
    else:
        aislix_analysis = build_shelf_only_analysis(products, count_validation=count_validation)
        aislix_key = "aislix_shelf_analysis"
    aislix_analysis["location_analysis"] = location_analysis

    reference_match = None
    if is_reference_comparison(metadata):
        document = metadata.get("reference_document")
        reference_match = build_reference_match(
            metadata["reference_items"],
            products,
            location_analysis,
            count_pending=not scan_complete,
            document=document if isinstance(document, dict) else None,
        )
        aislix_analysis["reference_match"] = reference_match

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

    out: dict[str, Any] = {
        "analysis_mode": analysis_mode,
        "scan_complete": scan_complete,
        "scan_status": "needs_review" if not scan_complete else "complete",
        "calc_engine_version": CALC_ENGINE_VERSION,
        "formula_version": FORMULA_VERSION,
        "astra_cv_analysis": astra_payload,
        "astra_cv_validation": count_validation,
        aislix_key: aislix_analysis,
        "calculated_metrics": calculated_metrics,
        "location_analysis": location_analysis,
        **({"reference_match": reference_match} if reference_match else {}),
        "execution_risk": execution_risk,
        "luna_secondary_analysis": luna_analysis,
        **summary_payload,
    }

    inventory_value = (
        aislix_analysis.get("inventory_value")
        if isinstance(aislix_analysis, dict)
        else None
    )
    if isinstance(inventory_value, dict) and inventory_value.get("priced_sku_count"):
        prior_fi = metadata.get("financial_impact")
        if not isinstance(prior_fi, dict):
            prior_fi = {}
        out["financial_impact"] = enrich_financial_impact_with_inventory(prior_fi, inventory_value)
        out["inventory_value"] = inventory_value

    return out
