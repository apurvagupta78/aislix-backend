"""Extract and attach Astra structured analysis from GPT vision JSON."""

from __future__ import annotations

from typing import Any

PLANOGRAM_MODE = "planogram_comparison"
SHELF_MODE = "image_only_shelf_analysis"


def detect_astra_mode(data: dict[str, Any], metadata: dict[str, Any] | None = None) -> str | None:
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
        facings = summary.get("visible_facings")
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
