"""Extract and attach Astra structured analysis from GPT vision JSON."""

from __future__ import annotations

from typing import Any

from app.astra_cv_validate import is_shelf_cv_payload

PLANOGRAM_MODE = "planogram_comparison"
SHELF_MODE = "image_only_shelf_analysis"
SHELF_CV_TYPE = "shelf_cv"


def detect_astra_mode(data: dict[str, Any], metadata: dict[str, Any] | None = None) -> str | None:
    if is_shelf_cv_payload(data):
        mode = str(data.get("analysis_mode") or "").strip().lower()
        if mode in {"with_planogram", "planogram_comparison"}:
            return PLANOGRAM_MODE
        if mode in {"no_planogram", "shelf_only", SHELF_MODE}:
            return SHELF_MODE
        if metadata:
            requested = str(metadata.get("analysis_mode") or "").strip().lower()
            if requested == "planogram_comparison":
                return PLANOGRAM_MODE
            if requested == "shelf_only":
                return SHELF_MODE

    mode = str(data.get("mode") or "").strip().lower()
    if mode == PLANOGRAM_MODE:
        return PLANOGRAM_MODE
    if mode in {SHELF_MODE, "shelf_only"}:
        return SHELF_MODE
    if metadata:
        analysis_mode = str(metadata.get("analysis_mode") or "").strip().lower()
        if analysis_mode == "planogram_comparison":
            return PLANOGRAM_MODE
        if analysis_mode == "shelf_only":
            return SHELF_MODE
    return None


def extract_astra_blocks(
    data: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Return (planogram_block, shelf_block, astra_mode)."""
    if is_shelf_cv_payload(data):
        mode = detect_astra_mode(data, metadata)
        if mode == PLANOGRAM_MODE:
            return data, None, mode
        if mode == SHELF_MODE:
            return None, data, mode

    nested_plano = data.get("astra_planogram_analysis")
    nested_shelf = data.get("astra_shelf_analysis")
    if isinstance(nested_plano, dict):
        return nested_plano, None, PLANOGRAM_MODE
    if isinstance(nested_shelf, dict):
        return None, nested_shelf, SHELF_MODE

    mode = detect_astra_mode(data, metadata)
    if mode == PLANOGRAM_MODE:
        return data, None, mode
    if mode == SHELF_MODE:
        return None, data, mode
    return None, None, None


def astra_product_rows(data: dict[str, Any], mode: str | None) -> list[dict[str, Any]]:
    rows = data.get("products") or data.get("rows") or data.get("Products")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    plano, shelf, _ = extract_astra_blocks(data)
    block = plano or shelf
    if not isinstance(block, dict):
        return []
    block_rows = block.get("products") or block.get("rows") or []
    if isinstance(block_rows, list):
        return [row for row in block_rows if isinstance(row, dict)]
    return []


def astra_products_to_inventory_rows(
    products: list[dict[str, Any]],
    *,
    mode: str | None,
) -> list[dict[str, Any]]:
    from app.make_scan import _map_make_products

    mapped: list[dict[str, Any]] = []
    for product in products:
        qty_raw = (
            product.get("actual_facings")
            or product.get("facings")
            or product.get("qty")
            or product.get("quantity")
        )
        try:
            qty = int(qty_raw or 0)
        except (TypeError, ValueError):
            qty = 0
        mapped.append(
            {
                **product,
                "product_name": product.get("product_name") or product.get("product") or product.get("name"),
                "product_category": (
                    product.get("product_category")
                    or product.get("category")
                    or product.get("subcategory")
                    or product.get("sub_category")
                ),
                "qty": max(1, qty) if qty > 0 else 1,
                "confidence": product.get("confidence") or 0.0,
            }
        )
    return _map_make_products(mapped)


def astra_executive_summary(data: dict[str, Any], mode: str | None) -> str | None:
    if is_shelf_cv_payload(data):
        return None

    for key in ("executive_summary", "summary_text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if not isinstance(summary, dict) or not summary:
        return None

    if mode == PLANOGRAM_MODE:
        compliance = summary.get("overall_planogram_compliance_percent") or summary.get(
            "overall_compliance_percent"
        )
        matched = summary.get("products_matched") or summary.get("matched_rows")
        total = summary.get("total_planogram_rows")
        parts = ["Planogram compliance audit complete."]
        if compliance is not None:
            parts.append(f"Overall compliance: {compliance}%.")
        if matched is not None and total is not None:
            parts.append(f"Matched {matched}/{total} planogram rows.")
        return " ".join(parts)

    if mode == SHELF_MODE:
        identified = summary.get("products_identified")
        facings = summary.get("visible_facings") or summary.get("total_actual_facings")
        parts = ["Shelf analysis complete."]
        if identified is not None:
            parts.append(f"Identified {identified} products.")
        if facings is not None:
            parts.append(f"Visible facings: {facings}.")
        return " ".join(parts)

    return None


def analysis_mode_label(mode: str | None, metadata: dict[str, Any] | None = None) -> str | None:
    if metadata:
        requested = str(metadata.get("analysis_mode") or "").strip()
        if requested:
            return requested
    if mode == PLANOGRAM_MODE:
        return "planogram_comparison"
    if mode == SHELF_MODE:
        return "shelf_only"
    return None


def _merge_shelf_pipeline(result: dict[str, Any], pipeline: dict[str, Any]) -> None:
    metrics = result.setdefault("metrics", {})
    if not isinstance(metrics, dict):
        return

    for key, value in pipeline.items():
        if key in {"executive_summary", "executive_summary_sections", "executive_summary_meta"}:
            continue
        metrics[key] = value

    if pipeline.get("executive_summary"):
        result["executive_summary"] = pipeline["executive_summary"]
        result["summary_text"] = pipeline["executive_summary"]
        metrics["executive_summary"] = pipeline["executive_summary"]
        metrics["executive_summary_sections"] = pipeline.get("executive_summary_sections")
        metrics["executive_summary_meta"] = pipeline.get("executive_summary_meta")

    if pipeline.get("aislix_planogram_analysis"):
        result["aislix_planogram_analysis"] = pipeline["aislix_planogram_analysis"]
    if pipeline.get("aislix_shelf_analysis"):
        result["aislix_shelf_analysis"] = pipeline["aislix_shelf_analysis"]

    if not pipeline.get("scan_complete", True):
        result["scan_status"] = pipeline.get("scan_status", "needs_review")
        metrics["scan_status"] = pipeline.get("scan_status", "needs_review")
        metrics["scan_complete"] = False


def attach_astra_to_scan_result(
    result: dict[str, Any],
    *,
    metadata: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    plano, shelf, mode = extract_astra_blocks(raw, metadata)
    analysis_mode = analysis_mode_label(mode, metadata)
    if analysis_mode:
        result["analysis_mode"] = analysis_mode

    if is_shelf_cv_payload(raw):
        metrics = result.get("metrics")
        if isinstance(metrics, dict) and metrics.get("calc_engine_version"):
            return result

        try:
            from app.luna_vision_scan import luna_required, run_luna_secondary_scan
            from app.shelf_pipeline import run_shelf_cv_pipeline

            luna_analysis = run_luna_secondary_scan(raw, metadata) if luna_required(metadata) else None
            legacy_plano = result.get("planogram_compliance")
            if not isinstance(legacy_plano, dict):
                if isinstance(metrics, dict) and isinstance(metrics.get("planogram_compliance"), dict):
                    legacy_plano = metrics["planogram_compliance"]

            pipeline = run_shelf_cv_pipeline(
                raw,
                metadata,
                luna_analysis=luna_analysis,
                legacy_planogram_compliance=legacy_plano if isinstance(legacy_plano, dict) else None,
            )
            if pipeline:
                _merge_shelf_pipeline(result, pipeline)
        except Exception as exc:
            print(f"attach_astra shelf_cv pipeline failed: {exc!r}")
            metrics = result.setdefault("metrics", {})
            if isinstance(metrics, dict):
                metrics["shelf_cv_pipeline_error"] = str(exc)[:500]
        return result

    if plano:
        result["astra_planogram_analysis"] = plano
    if shelf:
        result["astra_shelf_analysis"] = shelf
        for key in ("visible_prices", "visible_promotions", "shelf_issues"):
            values = shelf.get(key)
            if isinstance(values, list) and values:
                result[key] = values

    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        if analysis_mode:
            metrics["analysis_mode"] = analysis_mode
        if plano:
            metrics["astra_planogram_analysis"] = plano
        if shelf:
            metrics["astra_shelf_analysis"] = shelf

    retail = result.get("retail_intelligence")
    if isinstance(retail, dict):
        if plano:
            retail.setdefault("astra_planogram_analysis", plano)
        if shelf:
            retail.setdefault("astra_shelf_analysis", shelf)

    return result
