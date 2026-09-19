"""Astra comparison vision modes (expected products / planogram vs shelf)."""

from __future__ import annotations

from typing import Any

COMPARISON_MODES = frozenset({"expected_products", "planogram_comparison"})


def resolve_analysis_mode(metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("analysis_mode") or "").strip().lower()
    if explicit:
        return explicit
    if metadata.get("planogram_items"):
        return "planogram_comparison"
    if metadata.get("expected_products"):
        return "expected_products"
    return "shelf_only"


def is_astra_comparison_mode(mode: str) -> bool:
    return mode in COMPARISON_MODES


def build_vision_prompt_text(metadata: dict[str, Any]) -> str | None:
    prompt = str(metadata.get("vision_prompt") or "").strip()
    if not prompt:
        return None
    marker = "\n---\nAislix payload preview"
    if marker in prompt:
        prompt = prompt.split(marker, 1)[0].rstrip()
    return prompt or None


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def _looks_like_expected_products(products: list[Any]) -> bool:
    if not products or not isinstance(products[0], dict):
        return False
    sample = products[0]
    return any(
        key in sample
        for key in ("product_status", "facing_status", "overall_status", "category_status")
    )


def _looks_like_planogram_rows(rows: list[Any]) -> bool:
    if not rows or not isinstance(rows[0], dict):
        return False
    sample = rows[0]
    return any(
        key in sample
        for key in ("overall_row_status", "facing_compliance_percent", "brand_status")
    )


def _num(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize_expected_products(products: list[dict[str, Any]]) -> dict[str, Any]:
    matched = not_found = not_verifiable = below_facings = below_units = above_facings = above_units = 0
    for row in products:
        overall = str(row.get("overall_status") or "").upper()
        if overall in {"COMPLIANT", "PARTIALLY_COMPLIANT"}:
            matched += 1
        elif overall == "NOT_FOUND":
            not_found += 1
        elif overall == "NOT_VERIFIABLE":
            not_verifiable += 1
        facing_status = str(row.get("facing_status") or "").upper()
        if facing_status == "BELOW_EXPECTED":
            below_facings += 1
        elif facing_status == "ABOVE_EXPECTED":
            above_facings += 1
        unit_status = str(row.get("shelf_unit_status") or "").upper()
        if unit_status == "BELOW_EXPECTED":
            below_units += 1
        elif unit_status == "ABOVE_EXPECTED":
            above_units += 1
    return {
        "total_products": len(products),
        "matched_products": matched,
        "not_found_products": not_found,
        "not_verifiable_products": not_verifiable,
        "products_below_expected_facings": below_facings,
        "products_below_expected_units": below_units,
        "products_above_expected_facings": above_facings,
        "products_above_expected_units": above_units,
    }


def _summarize_planogram_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matched = not_found = non_compliant = not_verifiable = 0
    for row in rows:
        status = str(row.get("overall_row_status") or "").upper()
        if status == "COMPLIANT":
            matched += 1
        elif status == "NOT_FOUND":
            not_found += 1
        elif status in {"NON_COMPLIANT", "PARTIALLY_COMPLIANT"}:
            non_compliant += 1
        elif status == "NOT_VERIFIABLE":
            not_verifiable += 1
    total = len(rows)
    overall = round((matched / total) * 100, 2) if total else 0.0
    return {
        "total_planogram_rows": total,
        "matched_rows": matched,
        "not_found_rows": not_found,
        "non_compliant_rows": non_compliant,
        "not_verifiable_rows": not_verifiable,
        "overall_compliance_percent": overall,
    }


def extract_astra_analysis(
    raw: dict[str, Any],
    mode: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (response_key, block) when the model returned Astra comparison JSON."""
    if mode == "expected_products":
        block = _as_dict(raw.get("astra_expected_products_analysis"))
        products = _as_list(block.get("products")) if block else None
        if block and products:
            return "astra_expected_products_analysis", block

        products = _as_list(raw.get("products"))
        if products and _looks_like_expected_products(products):
            return "astra_expected_products_analysis", {
                "operating_model": raw.get("operating_model"),
                "image_quality": raw.get("image_quality"),
                "products": products,
                "summary": raw.get("summary") or _summarize_expected_products(products),
            }

    if mode == "planogram_comparison":
        block = _as_dict(raw.get("astra_planogram_analysis"))
        rows = _as_list(block.get("rows")) if block else None
        if block and rows:
            return "astra_planogram_analysis", block

        rows = _as_list(raw.get("rows"))
        if rows and _looks_like_planogram_rows(rows):
            return "astra_planogram_analysis", {
                "operating_model": raw.get("operating_model"),
                "image_quality": raw.get("image_quality"),
                "rows": rows,
                "summary": raw.get("summary") or _summarize_planogram_rows(rows),
            }

    return None, None


def inventory_from_astra_block(response_key: str, block: dict[str, Any]) -> list[dict[str, Any]]:
    if response_key == "astra_expected_products_analysis":
        return _inventory_from_expected_products(block.get("products") or [])
    if response_key == "astra_planogram_analysis":
        return _inventory_from_planogram_rows(block.get("rows") or [])
    return []


def _inventory_from_expected_products(products: list[Any]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for row in products:
        if not isinstance(row, dict):
            continue
        product_name = str(row.get("product_name") or row.get("product") or "").strip()
        if not product_name:
            continue
        actual_facings = _num(row.get("actual_facings"))
        actual_units = _num(row.get("actual_visible_units"))
        status = str(row.get("overall_status") or "").upper()
        qty = actual_units if actual_units > 0 else actual_facings
        if qty <= 0 and status not in {"NOT_FOUND", "NOT_VERIFIABLE"}:
            qty = 1
        inventory.append(
            {
                "brand": str(row.get("brand") or "Unknown").strip() or "Unknown",
                "product_name": product_name,
                "variant": str(row.get("variant") or "").strip(),
                "category": str(row.get("category") or row.get("sub_category") or "").strip(),
                "quantity": qty,
                "facings": actual_facings if actual_facings > 0 else max(qty, 0),
                "expected_facings": row.get("expected_facings"),
                "confidence": _float(row.get("confidence")),
                "stock_status": "out_of_stock" if status == "NOT_FOUND" else "in_stock",
                "counted_in_totals": True,
            }
        )
    return inventory


def _inventory_from_planogram_rows(rows: list[Any]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_name = str(row.get("product_name") or row.get("product") or "").strip()
        if not product_name:
            continue
        actual_facings = _num(row.get("actual_facings"))
        actual_units = _num(row.get("actual_visible_units"))
        status = str(row.get("overall_row_status") or "").upper()
        qty = actual_units if actual_units > 0 else actual_facings
        if qty <= 0 and status != "NOT_FOUND":
            qty = 1
        inventory.append(
            {
                "brand": str(row.get("brand") or "Unknown").strip() or "Unknown",
                "product_name": product_name,
                "variant": str(row.get("variant") or "").strip(),
                "location": str(row.get("location") or "").strip(),
                "quantity": qty,
                "facings": actual_facings if actual_facings > 0 else max(qty, 0),
                "expected_facings": row.get("expected_facings"),
                "confidence": _float(row.get("confidence")),
                "stock_status": "out_of_stock" if status == "NOT_FOUND" else "in_stock",
                "counted_in_totals": True,
            }
        )
    return inventory


def patch_parsed_for_astra_comparison(
    parsed: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    """Rewrite parsed inventory for Astra comparison responses."""
    mode = resolve_analysis_mode(metadata)
    if not is_astra_comparison_mode(mode):
        return parsed, None, None

    raw = parsed.get("raw")
    if not isinstance(raw, dict):
        return parsed, None, None

    response_key, block = extract_astra_analysis(raw, mode)
    if not response_key or not block:
        return parsed, None, None

    inventory = inventory_from_astra_block(response_key, block)
    if not inventory:
        return parsed, response_key, block

    return (
        {
            **parsed,
            "inventory": inventory,
            "is_full": False,
            "executive_summary": parsed.get("executive_summary")
            or f"Astra {mode.replace('_', ' ')} completed for {len(inventory)} item(s).",
        },
        response_key,
        block,
    )
