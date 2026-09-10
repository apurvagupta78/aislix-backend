"""End-to-end shelf scan pipeline."""

from __future__ import annotations

import base64
import csv
import io
import os
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
    load_image_bytes,
    load_image_from_url,
)
from app.sahi_detector import detection_mode_enabled, run_detection
from app.facing_filter import cluster_boxes_x_slots, filter_nested_facings, merge_boxes_by_column
from app.shelf_layout import ShelfMode, detect_shelf_mode
from app.inventory import aggregate_inventory, inventory_counted_rows, inventory_to_api_products, normalize_classified_labels
from app.metrics import (
    build_brand_share_payload,
    build_alerts,
    build_recommendations,
    category_breakdown,
    compute_metrics,
    executive_summary,
    ocr_quality_metrics,
)
from app.recognizer import classify_records
from app.report_generator import (
    annotated_image_dimensions,
    encode_annotated_image_bytes,
    encode_shelf_image_bytes,
    generate_annotated_image,
    generate_csv_bytes,
    generate_pdf_bytes,
)
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
        **ocr_quality_metrics(classified),
    }


def _detect_adaptive_boxes(image: np.ndarray) -> tuple[list, ShelfMode, dict]:
    """Pick YOLO confidence from shelf mode — close-up bin vs rack."""
    image_h, image_w = image.shape[:2]
    detection_stats: dict = {"detection_mode": "sahi" if detection_mode_enabled() else "standard"}

    probe_boxes, probe_stats = run_detection(image, conf=YOLO_CONF_MULTI_ROW)
    detection_stats.update(probe_stats)
    mode = detect_shelf_mode(probe_boxes, image_h, image_w)

    if mode == "single_bin":
        conf = YOLO_CONF_SINGLE_BIN
        boxes, pass_stats = run_detection(image, conf=conf)
        detection_stats.update(pass_stats)
        if len(boxes) > 10:
            boxes, retry_stats = run_detection(image, conf=YOLO_CONF_SINGLE_BIN_RETRY)
            detection_stats.update(retry_stats)
        boxes = cluster_boxes_x_slots(boxes)
    elif mode == "single_row":
        conf = YOLO_CONF_SINGLE_ROW
        boxes, pass_stats = run_detection(image, conf=conf)
        detection_stats.update(pass_stats)
        if len(boxes) > 12:
            boxes, retry_stats = run_detection(image, conf=YOLO_CONF_SINGLE_ROW_RETRY)
            detection_stats.update(retry_stats)
        boxes = merge_boxes_by_column(boxes)
    else:
        boxes = merge_boxes_by_column(probe_boxes)

    return boxes, mode, detection_stats


def _detect_boxes_for_scan(
    image: np.ndarray,
    metadata: dict,
    scan_context: dict,
) -> tuple[list, ShelfMode, dict]:
    """Adaptive YOLO plus optional planogram-guided gap-fill second pass."""
    boxes, shelf_mode, detection_stats = _detect_adaptive_boxes(image)
    gap_stats: dict = dict(detection_stats)

    planogram_items = metadata.get("planogram_items") or []
    candidates: list = []
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

    if candidates and len(boxes) < len(candidates):
        from app.planogram_gap_fill import fill_detection_gaps

        boxes, gap_stats = fill_detection_gaps(
            image,
            boxes,
            expected_count=len(candidates),
        )
        if gap_stats.get("gap_fill_regions"):
            print(
                "Gap-fill:",
                f"regions={gap_stats.get('gap_fill_regions')}",
                f"recovered={gap_stats.get('gap_fill_recovered')}",
                f"synthetic={gap_stats.get('gap_fill_synthetic', 0)}",
                f"final={gap_stats.get('gap_fill_final_boxes', len(boxes))}",
            )
        if shelf_mode == "single_row" and not gap_stats.get("gap_fill_synthetic"):
            boxes = merge_boxes_by_column(boxes)
        elif shelf_mode == "single_bin":
            boxes = cluster_boxes_x_slots(boxes)

    return boxes, shelf_mode, gap_stats


def run_scan_from_image(
    image: np.ndarray,
    scan_id: str | None = None,
    metadata: dict | None = None,
    *,
    image_url: str | None = None,
) -> dict:
    from app.make_scan import make_fallback_local, run_make_scan_from_image, use_make_provider
    from app.openai_vision_scan import run_openai_vision_scan_from_image, use_openai_provider

    if use_openai_provider():
        return run_openai_vision_scan_from_image(
            image,
            scan_id=scan_id,
            metadata=metadata,
            image_url=image_url,
        )

    if use_make_provider():
        try:
            return run_make_scan_from_image(
                image,
                scan_id=scan_id,
                metadata=metadata,
                image_url=image_url,
            )
        except Exception as exc:
            if make_fallback_local():
                print(f"Make scan failed, falling back to local pipeline: {exc}")
            else:
                raise

    started = time.time()
    scan_id = scan_id or uuid.uuid4().hex[:8]
    metadata = metadata or {}
    work_dir = None
    try:
        scan_context = resolve_scan_context(metadata)
        boxes, shelf_mode, gap_stats = _detect_boxes_for_scan(image, metadata, scan_context)
        if not boxes:
            raise ValueError("No products detected in this shelf image.")

        records, work_dir = crop_products(image, boxes)
        syn_centers = gap_stats.get("gap_fill_synthetic_centers") or []
        if syn_centers and records:
            widths = [float(r["x2"]) - float(r["x1"]) for r in records]
            tol = (sorted(widths)[len(widths) // 2] if widths else 80.0) * 0.35
            for rec in records:
                cx = (float(rec["x1"]) + float(rec["x2"])) / 2.0
                if any(abs(cx - float(sc)) <= tol for sc in syn_centers):
                    rec["gap_fill_synthetic"] = True
        scan_context["shelf_mode"] = shelf_mode
        scan_context["shelf_layout"] = "single_row" if shelf_mode != "multi_row" else "multi_row"
        scan_category = scan_context.get("aislix_category") or metadata.get("category") or metadata.get("shelf_label")

        planogram_items = metadata.get("planogram_items") or []

        classified, recognition_engine_stats = classify_records(
            records,
            scan_id=scan_id,
            scan_category=scan_category,
            scan_context=scan_context,
            source_image=image,
        )
        classified = normalize_classified_labels(classified)
        classified = filter_nested_facings(classified, layout=shelf_mode)
        from app.snack_row_recovery import (
            enforce_snack_color_and_brand_labels,
            finalize_lays_rack_labels,
            mark_top_partial_exclusions,
            recover_snack_variants_by_row,
        )

        if not scan_context.get("planogram_candidates"):
            classified, row_stats = recover_snack_variants_by_row(
                classified,
                image,
                scan_context,
            )
            recognition_engine_stats.update(row_stats)
        classified, color_fixes = enforce_snack_color_and_brand_labels(
            classified, image, scan_context
        )
        if color_fixes:
            recognition_engine_stats["snack_color_fix"] = color_fixes
        from app.pc_row_recovery import recover_pc_unknowns_by_row

        from app.pc_pack_text_guard import enforce_pc_pack_text_labels, reconcile_pc_rows_by_type

        classified, pc_guard_stats = enforce_pc_pack_text_labels(classified, scan_context)
        if pc_guard_stats.get("pc_pack_text_fix") or pc_guard_stats.get("pc_pack_text_reject"):
            recognition_engine_stats.update(pc_guard_stats)
        classified, pc_type_stats = reconcile_pc_rows_by_type(classified, scan_context)
        if pc_type_stats.get("pc_row_type_fix") or pc_type_stats.get("pc_row_type_reject"):
            recognition_engine_stats.update(pc_type_stats)
        classified, pc_stats = recover_pc_unknowns_by_row(classified, scan_context)
        if pc_stats.get("pc_row_recovery"):
            recognition_engine_stats.update(pc_stats)
        classified, pc_guard_stats2 = enforce_pc_pack_text_labels(classified, scan_context)
        if pc_guard_stats2.get("pc_pack_text_fix") or pc_guard_stats2.get("pc_pack_text_reject"):
            for key in ("pc_pack_text_fix", "pc_pack_text_reject"):
                recognition_engine_stats[key] = int(recognition_engine_stats.get(key) or 0) + int(
                    pc_guard_stats2.get(key) or 0
                )
        classified, pc_type_stats2 = reconcile_pc_rows_by_type(classified, scan_context)
        if pc_type_stats2.get("pc_row_type_fix") or pc_type_stats2.get("pc_row_type_reject"):
            for key in ("pc_row_type_fix", "pc_row_type_reject"):
                recognition_engine_stats[key] = int(recognition_engine_stats.get(key) or 0) + int(
                    pc_type_stats2.get(key) or 0
                )
        if scan_context.get("planogram_mode") and scan_context.get("planogram_candidates"):
            from app.planogram_guided import (
                assign_planogram_shelf_rows,
                assign_planogram_slots,
                should_use_planogram_shelf_rows,
                should_use_planogram_slots,
            )

            planogram_candidates = scan_context["planogram_candidates"]
            if should_use_planogram_shelf_rows(classified, planogram_candidates, scan_context):
                classified = assign_planogram_shelf_rows(
                    classified,
                    planogram_candidates,
                    scan_id=scan_id,
                    scan_context=scan_context,
                    source_image=image,
                )
                scan_context["planogram_shelf_rows"] = True
            elif should_use_planogram_slots(classified, planogram_candidates, scan_context):
                classified = assign_planogram_slots(
                    classified,
                    planogram_candidates,
                    scan_id=scan_id,
                    scan_context=scan_context,
                )
            else:
                scan_context["planogram_slot_skipped"] = True

            from app.planogram_guided import recover_planogram_unknowns_with_gpt

            classified, gpt_recovery_stats = recover_planogram_unknowns_with_gpt(
                classified,
                scan_context=scan_context,
                scan_id=scan_id,
            )
            from app.snack_row_recovery import recover_snack_variants_by_row

            classified, row_override_stats = recover_snack_variants_by_row(
                classified,
                image,
                scan_context,
                override_only=True,
            )
            recognition_engine_stats.update(row_override_stats)
            recognition_engine_stats["gpt_recovery"] = gpt_recovery_stats.get("gpt_recovery", 0)
            recognition_engine_stats["gpt_calls"] = int(
                recognition_engine_stats.get("gpt_calls") or 0
            ) + int(gpt_recovery_stats.get("gpt_calls") or 0)
            recognition_engine_stats["gpt"] = int(
                recognition_engine_stats.get("gpt") or 0
            ) + int(gpt_recovery_stats.get("gpt") or 0)
            classified, color_fixes = enforce_snack_color_and_brand_labels(
                classified, image, scan_context
            )
            if color_fixes:
                recognition_engine_stats["snack_color_fix"] = color_fixes
        classified, lays_finalize = finalize_lays_rack_labels(classified, image, scan_context)
        if lays_finalize:
            recognition_engine_stats["lays_rack_finalize"] = lays_finalize
        classified, top_partial_excluded = mark_top_partial_exclusions(classified, image, scan_context)
        if top_partial_excluded:
            recognition_engine_stats["top_partial_excluded"] = top_partial_excluded
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
                inventory=inventory_counted_rows(inventory),
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
        from app.recognizer import active_recognition_mode

        metrics["recognition_mode"] = (
            "planogram_guided" if scan_context.get("planogram_candidates") else active_recognition_mode()
        )
        metrics["gpt_vision_calls"] = int(recognition_engine_stats.get("gpt_calls") or 0)
        if recognition_engine_stats.get("ocr_empty") is not None:
            metrics["ocr_empty_facings"] = int(recognition_engine_stats.get("ocr_empty") or 0)
        if recognition_engine_stats.get("snack_row_recovery"):
            metrics["snack_row_recovery"] = int(recognition_engine_stats["snack_row_recovery"])
        if scan_context.get("planogram_mode"):
            metrics["planogram_guided_recognition"] = True
            metrics["planogram_candidate_count"] = len(scan_context.get("planogram_candidates") or [])
            if scan_context.get("planogram_shelf_rows"):
                metrics["planogram_shelf_rows"] = True
            if recognition_engine_stats.get("gpt_recovery"):
                metrics["planogram_gpt_recovery"] = recognition_engine_stats["gpt_recovery"]
        if gap_stats:
            metrics.update({k: v for k, v in gap_stats.items() if k != "gap_fill_enabled"})
            metrics["planogram_gap_fill"] = bool(gap_stats.get("gap_fill_recovered"))
            if gap_stats.get("sahi_enabled"):
                metrics["detection_mode"] = "sahi"
            elif gap_stats.get("detection_mode"):
                metrics["detection_mode"] = gap_stats["detection_mode"]
        if planogram_compliance:
            metrics["planogram_compliance_percent"] = planogram_compliance.get("compliance_percent")
            metrics["planogram_sku_match_percent"] = planogram_compliance.get("planogram_sku_match_percent")
            metrics["planogram_qty_compliance_percent"] = planogram_compliance.get(
                "planogram_qty_compliance_percent"
            )
            metrics["planogram_summary"] = planogram_compliance.get("summary")
        from app.metrics import compute_financial_impact, finalize_execution_score

        finalize_execution_score(metrics)
        metrics["financial_impact"] = compute_financial_impact(
            inventory,
            metrics,
            planogram_items=planogram_items or None,
            planogram_compliance=planogram_compliance,
        )
        share_payload = build_brand_share_payload(
            inventory,
            audit_sub_category=scan_context.get("sub_category"),
        )
        shares = share_payload["brand_share"]
        metrics["top_brands"] = share_payload["top_brands"]
        metrics["brand_share_scope"] = share_payload["brand_share_scope"]
        metrics["brand_share_denominator"] = share_payload["brand_share_denominator"]
        from app.metrics import compute_competitor_intel

        primary_brand = metadata.get("primary_brand") or scan_context.get("primary_brand")
        competitor_brands = metadata.get("competitor_brands") or scan_context.get("competitor_brands")
        competitor_intel = compute_competitor_intel(
            shares,
            primary_brand=str(primary_brand) if primary_brand else None,
            competitor_brands=list(competitor_brands) if isinstance(competitor_brands, list) else None,
        )
        if competitor_intel:
            metrics["competitor_intel"] = competitor_intel
        categories = category_breakdown(inventory_counted_rows(inventory))
        alerts = build_alerts(metrics, compliance_alerts=compliance_alerts)
        recommendations = build_recommendations(metrics, inventory, compliance_alerts=compliance_alerts)
        summary_text = executive_summary(metrics, compliance_alerts=compliance_alerts)

        from app.learned_catalog import count_learned, flush_learned, pop_learned_updates

        flush_learned()
        learned_updates = pop_learned_updates()

        export_facings = metadata.get("export_facings") or os.getenv(
            "SCAN_EXPORT_FACINGS", ""
        ).lower() in {"1", "true", "yes"}

        annotated = generate_annotated_image(image, classified)
        original_jpeg = encode_shelf_image_bytes(image)
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
        csv_b64 = base64.b64encode(
            generate_csv_bytes(
                inventory,
                scan_id=scan_id,
                metrics=metrics,
                shares=shares,
                recommendations=recommendations,
                alerts=alerts,
                compliance_alerts=compliance_alerts,
                executive_summary=summary_text,
            )
        ).decode("utf-8")

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
            "learned_updates": learned_updates,
            "learned_catalog_size": count_learned(),
            "learned_new_this_scan": len(learned_updates),
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
                        "pack_text": (r.get("pack_text") or "")[:240],
                        "ocr_confidence": r.get("ocr_confidence"),
                        "ocr_variant": r.get("ocr_variant"),
                    }
                    for r in classified
                ]
                if export_facings
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
                "shelf_mode": shelf_mode,
            },
        }
    finally:
        if work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def run_scan_from_bytes(data: bytes, **kwargs) -> dict:
    return run_scan_from_image(load_image_bytes(data), **kwargs)


def run_scan_from_url(url: str, **kwargs) -> dict:
    return run_scan_from_image(load_image_from_url(url), image_url=url, **kwargs)
