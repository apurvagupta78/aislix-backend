"""End-to-end shelf scan pipeline."""

from __future__ import annotations

import base64
import csv
import io
import shutil
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from app.detector import (
    YOLO_CONF_MULTI_ROW,
    YOLO_CONF_SINGLE_BIN,
    YOLO_CONF_SINGLE_BIN_RETRY,
    YOLO_CONF_SINGLE_ROW,
    YOLO_CONF_SINGLE_ROW_RETRY,
    crop_products,
    detect_products,
    get_boxes,
    load_image_bytes,
    load_image_from_url,
)
from app.facing_filter import cluster_boxes_x_slots, filter_nested_facings, merge_boxes_by_column
from app.shelf_layout import ShelfMode, detect_shelf_mode
from app.inventory import aggregate_inventory, inventory_to_api_products
from app.metrics import (
    brand_share,
    build_alerts,
    build_recommendations,
    category_breakdown,
    compute_metrics,
    executive_summary,
)
from app.recognizer import classify_records
from app.report_generator import generate_annotated_image, generate_csv_bytes, generate_pdf_bytes
from app.scan_context import resolve_scan_context
from app.subcategory_compliance import (
    analyze_subcategory_compliance,
    apply_compliance_to_inventory,
)

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "assets" / "aislix_logo.png"


def _recognition_stats(classified: list[dict]) -> dict:
    counts = {"ocr": 0, "gpt": 0, "faiss": 0, "learned": 0, "propagate": 0, "none": 0}
    for item in classified:
        source = (item.get("recognition_source") or "none").lower()
        if source.startswith("ocr"):
            counts["ocr"] += 1
        elif source.startswith("gpt"):
            counts["gpt"] += 1
        elif source == "propagate":
            counts["propagate"] += 1
        elif source == "learned":
            counts["learned"] += 1
        elif source == "faiss":
            counts["faiss"] += 1
        elif source == "none" or (item.get("brand") or "").lower() == "unknown":
            counts["none"] += 1
        else:
            counts["faiss"] += 1
    return {
        "recognition_ocr": counts["ocr"],
        "recognition_gpt": counts["gpt"],
        "recognition_faiss": counts["faiss"],
        "recognition_learned": counts["learned"],
        "recognition_propagate": counts["propagate"],
        "recognition_unknown": counts["none"],
    }


def _detect_adaptive_boxes(image: np.ndarray) -> tuple[list, ShelfMode]:
    """Pick YOLO confidence from shelf mode — close-up bin vs rack."""
    image_h, image_w = image.shape[:2]
    max_x = image_w

    probe_results, pad_x = detect_products(image, conf=YOLO_CONF_MULTI_ROW)
    probe_boxes = get_boxes(probe_results, pad_x=pad_x, max_x=max_x)
    mode = detect_shelf_mode(probe_boxes, image_h, image_w)

    if mode == "single_bin":
        conf = YOLO_CONF_SINGLE_BIN
        results, pad_x = detect_products(image, conf=conf)
        boxes = get_boxes(results, pad_x=pad_x, max_x=max_x)
        if len(boxes) > 10:
            results, pad_x = detect_products(image, conf=YOLO_CONF_SINGLE_BIN_RETRY)
            boxes = get_boxes(results, pad_x=pad_x, max_x=max_x)
        boxes = cluster_boxes_x_slots(boxes)
    elif mode == "single_row":
        conf = YOLO_CONF_SINGLE_ROW
        results, pad_x = detect_products(image, conf=conf)
        boxes = get_boxes(results, pad_x=pad_x, max_x=max_x)
        if len(boxes) > 12:
            results, pad_x = detect_products(image, conf=YOLO_CONF_SINGLE_ROW_RETRY)
            boxes = get_boxes(results, pad_x=pad_x, max_x=max_x)
        boxes = merge_boxes_by_column(boxes)
    else:
        boxes = merge_boxes_by_column(probe_boxes)

    return boxes, mode


def run_scan_from_image(image: np.ndarray, scan_id: str | None = None, metadata: dict | None = None) -> dict:
    started = time.time()
    scan_id = scan_id or uuid.uuid4().hex[:8]
    metadata = metadata or {}
    work_dir = None
    try:
        boxes, shelf_mode = _detect_adaptive_boxes(image)
        if not boxes:
            raise ValueError("No products detected in this shelf image.")

        records, work_dir = crop_products(image, boxes)
        scan_context = resolve_scan_context(metadata)
        scan_context["shelf_mode"] = shelf_mode
        scan_context["shelf_layout"] = "single_row" if shelf_mode != "multi_row" else "multi_row"
        scan_category = scan_context.get("aislix_category") or metadata.get("category") or metadata.get("shelf_label")

        planogram_items = metadata.get("planogram_items") or []
        if planogram_items:
            from app.planogram_guided import prepare_planogram_candidates

            candidates = prepare_planogram_candidates(
                planogram_items,
                metadata.get("assignment_scope_type"),
                metadata.get("assignment_scope_values") or {},
                scan_context,
            )
            if candidates:
                scan_context["planogram_mode"] = True
                scan_context["planogram_candidates"] = candidates

        classified, recognition_engine_stats = classify_records(
            records,
            scan_id=scan_id,
            scan_category=scan_category,
            scan_context=scan_context,
        )
        classified = filter_nested_facings(classified, layout=shelf_mode)
        compliance = analyze_subcategory_compliance(classified, scan_context)
        classified = compliance["classified"]
        subcategory_mismatches = compliance["subcategory_mismatches"]
        compliance_alerts = compliance["compliance_alerts"]
        misplaced_facings = compliance["misplaced_facings"]

        inventory = aggregate_inventory(classified)
        inventory = apply_compliance_to_inventory(inventory, subcategory_mismatches)

        planogram_compliance = None
        if planogram_items:
            from app.planogram_compliance import compare_planogram

            planogram_compliance = compare_planogram(
                planogram_items=planogram_items,
                inventory=inventory,
                scan_context=scan_context,
                scope_type=metadata.get("assignment_scope_type"),
                scope_values=metadata.get("assignment_scope_values") or {},
                full_store_items=metadata.get("planogram_items_full") or planogram_items,
            )
            metrics_planogram = planogram_compliance.get("compliance_percent")
            if metrics_planogram is not None:
                # surfaced to Lovable → shelf_scans.planogram_compliance_percent
                scan_context["planogram_compliance_percent"] = metrics_planogram

        products = inventory_to_api_products(inventory)
        processing_ms = int((time.time() - started) * 1000)
        metrics = compute_metrics(
            inventory,
            classified,
            image.shape,
            processing_ms,
            misplaced_facings=misplaced_facings,
        )
        recognition_stats = _recognition_stats(classified)
        metrics.update(recognition_stats)
        metrics["gpt_vision_calls"] = int(recognition_engine_stats.get("gpt_calls") or 0)
        if scan_context.get("planogram_mode"):
            metrics["planogram_guided_recognition"] = True
            metrics["planogram_candidate_count"] = len(scan_context.get("planogram_candidates") or [])
        if planogram_compliance:
            metrics["planogram_compliance_percent"] = planogram_compliance.get("compliance_percent")
            metrics["planogram_summary"] = planogram_compliance.get("summary")
        shares = brand_share(inventory)
        categories = category_breakdown(inventory)
        alerts = build_alerts(metrics, compliance_alerts=compliance_alerts)
        recommendations = build_recommendations(metrics, inventory, compliance_alerts=compliance_alerts)
        summary_text = executive_summary(metrics, compliance_alerts=compliance_alerts)

        from app.learned_catalog import count_learned, flush_learned, pop_learned_updates

        flush_learned()
        learned_updates = pop_learned_updates()

        annotated = generate_annotated_image(image, classified)
        _, encoded = cv2.imencode(".jpg", annotated)
        annotated_b64 = base64.b64encode(encoded.tobytes()).decode("utf-8")

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
        )
        csv_b64 = base64.b64encode(generate_csv_bytes(inventory)).decode("utf-8")

        return {
            "scan_id": scan_id,
            "model_version": "yolov8+ocr+faiss+clip+gpt-v2",
            "executive_summary": summary_text,
            "summary_text": summary_text,
            "metrics": metrics,
            "summary": metrics,
            "total_products": metrics["total_products"],
            "products": products,
            "inventory": inventory,
            "brand_share": shares,
            "top_brands": shares[:10],
            "category_breakdown": categories,
            "alerts": alerts,
            "compliance_alerts": compliance_alerts,
            "subcategory_mismatches": subcategory_mismatches,
            "recommendations": recommendations,
            "annotated_image_base64": annotated_b64,
            "planogram_compliance": planogram_compliance,
            "assignment_id": metadata.get("assignment_id"),
            "pdf_base64": pdf_b64,
            "csv_base64": csv_b64,
            "learned_updates": learned_updates,
            "learned_catalog_size": count_learned(),
            "learned_new_this_scan": len(learned_updates),
            "store_id": scan_context.get("store_id"),
            "shelf_label": scan_context.get("shelf_label") or metadata.get("shelf_label"),
            "category": scan_context.get("aislix_category") or metadata.get("category"),
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
                "shelf_mode": shelf_mode,
            },
        }
    finally:
        if work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def run_scan_from_bytes(data: bytes, **kwargs) -> dict:
    return run_scan_from_image(load_image_bytes(data), **kwargs)


def run_scan_from_url(url: str, **kwargs) -> dict:
    return run_scan_from_image(load_image_from_url(url), **kwargs)
