"""Post-process Make.com partial/full scan responses into Aislix scan payloads."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import numpy as np

from app.inventory import (
    aggregate_inventory,
    fix_gpt_brand_hallucinations,
    inventory_counted_rows,
    inventory_to_api_products,
    merge_inventory_rows,
    normalize_classified_labels,
)
from app.metrics import (
    build_alerts,
    build_brand_share_payload,
    build_recommendations,
    category_breakdown,
    compute_metrics,
    executive_summary,
)
from app.report_generator import (
    annotated_image_dimensions,
    encode_annotated_image_bytes,
    encode_shelf_image_bytes,
    generate_annotated_image,
    generate_csv_bytes,
    generate_pdf_bytes,
)
from app.scan_context import resolve_scan_context
from app.subcategory_compliance import analyze_subcategory_compliance, apply_compliance_to_inventory

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "assets" / "aislix_logo.png"
MODEL_VERSION = "make.com"


def _has_bbox_facings(classified: list[dict]) -> bool:
    for row in classified:
        x1, y1, x2, y2 = int(row.get("x1", 0)), int(row.get("y1", 0)), int(row.get("x2", 0)), int(row.get("y2", 0))
        if x2 > x1 and y2 > y1:
            return True
    return False


def _normalize_facing_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["recognition_source"] = out.get("recognition_source") or "make.com"
    for key in ("x1", "y1", "x2", "y2"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


def _expand_inventory_to_classified(inventory: list[dict]) -> list[dict]:
    classified: list[dict] = []
    for row in inventory:
        qty = max(1, int(row.get("facings") or row.get("quantity") or 1))
        pack_text = (row.get("pack_text") or "").strip() or " ".join(
            filter(
                None,
                [
                    row.get("brand"),
                    row.get("product_name"),
                    row.get("variant"),
                    row.get("product_category"),
                ],
            )
        )
        for _ in range(qty):
            classified.append(
                {
                    "brand": row.get("brand") or "Unknown",
                    "product_name": row.get("product_name") or "Unknown",
                    "variant": row.get("variant") or "",
                    "category": row.get("category") or row.get("product_category") or "General",
                    "sku": row.get("sku") or "",
                    "confidence": float(row.get("confidence") or 0.0),
                    "pack_text": pack_text,
                    "recognition_source": "make.com",
                    "x1": 0,
                    "y1": 0,
                    "x2": 0,
                    "y2": 0,
                }
            )
    return classified


def _normalize_inventory_rows(rows: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        item = dict(row)
        qty = int(item.get("quantity") or item.get("facings") or 0)
        item.setdefault("quantity", qty)
        item.setdefault("facings", qty or item.get("facings") or 0)
        item.setdefault("counted_in_totals", True)
        item.setdefault("stock_status", "in_stock" if qty > 2 else "low_stock")
        normalized.append(item)
    return normalized


def _enrich_full_response(data: dict[str, Any], scan_id: str) -> dict[str, Any]:
    out = dict(data)
    out["scan_id"] = out.get("scan_id") or scan_id
    out["model_version"] = MODEL_VERSION
    out.setdefault("summary_text", out.get("executive_summary"))
    if out.get("metrics") and not out.get("summary"):
        out["summary"] = out["metrics"]
    if out.get("metrics") and "total_products" not in out:
        out["total_products"] = out["metrics"].get("total_products")
    return out


def finalize_make_scan(
    image: np.ndarray,
    *,
    scan_id: str,
    metadata: dict[str, Any],
    parsed: dict[str, Any],
    processing_ms: int,
) -> dict[str, Any]:
    if parsed.get("is_full"):
        return _enrich_full_response(parsed["raw"], scan_id)

    scan_context = resolve_scan_context(metadata)
    raw = parsed["raw"]
    inventory = parsed.get("inventory")
    make_annotated_b64 = parsed.get("annotated_image_base64")
    planogram_items = metadata.get("planogram_items") or []

    openai_facings_for_annotate: list[dict] = []
    if parsed.get("product_rows"):
        from app.make_scan import build_facings_from_make_products

        openai_facings_for_annotate = build_facings_from_make_products(
            parsed["product_rows"],
            image.shape,
        )

    classified: list[dict]
    if inventory:
        inventory = _normalize_inventory_rows(inventory)
        if planogram_items:
            from app.make_annotate import apply_planogram_yolo_qty

            inventory, yolo_qty_applied, yolo_qty_meta = apply_planogram_yolo_qty(
                image,
                metadata,
                scan_context,
                inventory,
                planogram_items,
            )
            if yolo_qty_applied:
                scan_context["planogram_yolo_qty"] = True
            if yolo_qty_meta.get("yolo_row_counts"):
                scan_context["yolo_row_counts"] = yolo_qty_meta["yolo_row_counts"]
            if yolo_qty_meta.get("yolo_ideal_row_spans"):
                scan_context["yolo_ideal_row_spans"] = yolo_qty_meta["yolo_ideal_row_spans"]
            if yolo_qty_meta.get("yolo_row_spans"):
                scan_context["yolo_row_spans"] = yolo_qty_meta["yolo_row_spans"]
            if yolo_qty_meta.get("yolo_row_imputed"):
                scan_context["yolo_row_imputed"] = True
        inventory = fix_gpt_brand_hallucinations(inventory)
        inventory = merge_inventory_rows(inventory)
        classified = normalize_classified_labels(_expand_inventory_to_classified(inventory))
    elif parsed.get("facings"):
        facings = parsed.get("facings") or []
        classified = normalize_classified_labels([_normalize_facing_row(row) for row in facings])
        inventory = aggregate_inventory(classified)
    else:
        from app.make_scan import make_missing_products_message

        raise ValueError(make_missing_products_message(raw))

    compliance = analyze_subcategory_compliance(classified, scan_context)
    classified = compliance["classified"]
    subcategory_mismatches = compliance["subcategory_mismatches"]
    compliance_alerts = compliance["compliance_alerts"]
    misplaced_facings = compliance["misplaced_facings"]
    inventory = apply_compliance_to_inventory(inventory, subcategory_mismatches)

    planogram_compliance = None
    if planogram_items:
        from app.planogram_compliance import compare_planogram

        planogram_compliance = compare_planogram(
            planogram_items=planogram_items,
            inventory=inventory_counted_rows(inventory),
            scan_context=scan_context,
            scope_type=metadata.get("assignment_scope_type"),
            scope_values=metadata.get("assignment_scope_values") or {},
            full_store_items=metadata.get("planogram_items_full") or planogram_items,
        )
        metrics_planogram = planogram_compliance.get("compliance_percent")
        if metrics_planogram is not None:
            scan_context["planogram_compliance_percent"] = metrics_planogram

    products = inventory_to_api_products(inventory)
    metrics = compute_metrics(
        inventory,
        classified,
        image.shape,
        processing_ms,
        misplaced_facings=misplaced_facings,
    )
    metrics["recognition_mode"] = "make.com"
    metrics["detection_mode"] = "make.com"
    if planogram_compliance:
        metrics["planogram_compliance_percent"] = planogram_compliance.get("compliance_percent")
        metrics["planogram_sku_match_percent"] = planogram_compliance.get("planogram_sku_match_percent")
        metrics["planogram_qty_compliance_percent"] = planogram_compliance.get("planogram_qty_compliance_percent")
        metrics["planogram_summary"] = planogram_compliance.get("summary")
    if scan_context.get("planogram_yolo_qty"):
        metrics["planogram_yolo_qty"] = True
    if scan_context.get("yolo_row_counts"):
        metrics["yolo_row_counts"] = scan_context["yolo_row_counts"]
    if scan_context.get("yolo_ideal_row_spans"):
        metrics["yolo_ideal_row_spans"] = scan_context["yolo_ideal_row_spans"]
    if scan_context.get("yolo_row_spans"):
        metrics["yolo_row_spans"] = scan_context["yolo_row_spans"]
    if scan_context.get("yolo_row_imputed"):
        metrics["yolo_row_imputed"] = True

    share_payload = build_brand_share_payload(
        inventory,
        audit_sub_category=scan_context.get("sub_category"),
    )
    shares = share_payload["brand_share"]
    metrics["top_brands"] = share_payload["top_brands"]
    metrics["brand_share_scope"] = share_payload["brand_share_scope"]
    metrics["brand_share_denominator"] = share_payload["brand_share_denominator"]
    categories = category_breakdown(inventory_counted_rows(inventory))
    alerts = build_alerts(metrics, compliance_alerts=compliance_alerts)
    recommendations = build_recommendations(metrics, inventory, compliance_alerts=compliance_alerts)
    summary_text = parsed.get("executive_summary") or raw.get("summary_text") or executive_summary(
        metrics, compliance_alerts=compliance_alerts
    )

    export_facings = metadata.get("export_facings") or os.getenv(
        "SCAN_EXPORT_FACINGS", ""
    ).lower() in {"1", "true", "yes"}

    annotated_source = classified
    if make_annotated_b64:
        annotated = None
        metrics["detection_mode"] = "make.com+openai_image"
    else:
        from app.make_annotate import build_make_annotated_facings, make_annotate_draw_labels

        annotate_facings, annotate_mode = build_make_annotated_facings(
            image,
            inventory,
            metadata=metadata,
            scan_context=scan_context,
            planogram_items=planogram_items,
            openai_facings=openai_facings_for_annotate,
            product_rows=parsed.get("product_rows"),
        )
        if annotate_facings:
            draw_labels = make_annotate_draw_labels()
            if annotate_mode == "make.com+yolo_overlay":
                annotated_source = annotate_facings
            else:
                compliance_local = analyze_subcategory_compliance(annotate_facings, scan_context)
                annotated_source = compliance_local["classified"]
            annotated = generate_annotated_image(
                image,
                annotated_source,
                draw_labels=draw_labels,
            )
            metrics["detection_mode"] = annotate_mode
        else:
            annotated = image.copy()

    original_jpeg = encode_shelf_image_bytes(image)
    if make_annotated_b64:
        try:
            annotated_jpeg = base64.b64decode(make_annotated_b64)
            annotated_dims = annotated_image_dimensions(image)
        except Exception:
            annotated_jpeg = encode_annotated_image_bytes(image.copy())
            annotated_dims = annotated_image_dimensions(image)
    else:
        annotated_jpeg = encode_annotated_image_bytes(annotated)
        annotated_dims = annotated_image_dimensions(annotated)
    original_b64 = base64.b64encode(original_jpeg).decode("utf-8")
    annotated_b64 = base64.b64encode(annotated_jpeg).decode("utf-8")
    metrics["annotated_image_width"] = annotated_dims["width"]
    metrics["annotated_image_height"] = annotated_dims["height"]
    metrics["original_image_width"] = annotated_dims["width"]
    metrics["original_image_height"] = annotated_dims["height"]

    pdf_b64 = generate_pdf_bytes(
        scan_id=scan_id,
        metrics=metrics,
        inventory=inventory,
        shares=shares,
        recommendations=recommendations,
        alerts=alerts,
        compliance_alerts=compliance_alerts,
        subcategory_mismatches=subcategory_mismatches,
        executive_summary=summary_text,
        logo_path=LOGO_PATH if LOGO_PATH.exists() else None,
        annotated_jpeg=annotated_jpeg,
    )
    csv_b64 = base64.b64encode(generate_csv_bytes(inventory)).decode("utf-8")

    return {
        "scan_id": scan_id,
        "model_version": MODEL_VERSION,
        "executive_summary": summary_text,
        "summary_text": summary_text,
        "metrics": metrics,
        "summary": metrics,
        "total_products": metrics["total_products"],
        "products": products,
        "inventory": inventory,
        "brand_share": shares,
        "top_brands": share_payload["top_brands"],
        "brand_share_all": share_payload["brand_share_all"],
        "brand_share_scope": share_payload["brand_share_scope"],
        "brand_share_denominator": share_payload["brand_share_denominator"],
        "category_breakdown": categories,
        "alerts": alerts,
        "compliance_alerts": compliance_alerts,
        "subcategory_mismatches": subcategory_mismatches,
        "recommendations": recommendations,
        "annotated_image_base64": annotated_b64,
        "annotated_image_mime": "image/jpeg",
        "annotated_image_width": annotated_dims["width"],
        "annotated_image_height": annotated_dims["height"],
        "original_image_base64": original_b64,
        "original_image_mime": "image/jpeg",
        "original_image_width": annotated_dims["width"],
        "original_image_height": annotated_dims["height"],
        "planogram_compliance": planogram_compliance,
        "assignment_id": metadata.get("assignment_id"),
        "pdf_base64": pdf_b64,
        "csv_base64": csv_b64,
        "learned_updates": [],
        "learned_catalog_size": 0,
        "learned_new_this_scan": 0,
        "store_id": scan_context.get("store_id"),
        "shelf_label": scan_context.get("shelf_label") or metadata.get("shelf_label"),
        "category": scan_context.get("aislix_category") or metadata.get("category"),
        "facings_debug": (
            [
                {
                    "x1": int(r["x1"]),
                    "y1": int(r["y1"]),
                    "x2": int(r["x2"]),
                    "y2": int(r["y2"]),
                    "brand": r.get("brand"),
                    "product_name": r.get("product_name"),
                    "sku": r.get("sku"),
                    "confidence": r.get("confidence"),
                    "recognition_source": r.get("recognition_source"),
                }
                for r in annotated_source
            ]
            if export_facings and _has_bbox_facings(annotated_source)
            else None
        ),
        "scan_context": {
            "aislix_category": scan_context.get("aislix_category"),
            "aislix_category_id": scan_context.get("aislix_category_id"),
            "sub_category": scan_context.get("sub_category"),
            "sub_category_label": scan_context.get("sub_category_label"),
            "sub_category_custom": scan_context.get("sub_category_custom"),
            "location": scan_context.get("location"),
            "shelf_label": scan_context.get("shelf_label"),
            "store_id": scan_context.get("store_id"),
            "shelf_layout": scan_context.get("shelf_layout"),
            "shelf_mode": scan_context.get("shelf_mode"),
        },
    }
