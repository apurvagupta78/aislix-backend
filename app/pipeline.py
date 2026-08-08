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
    crop_products,
    detect_products,
    get_boxes,
    load_image_bytes,
    load_image_from_url,
)
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

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "assets" / "aislix_logo.png"


def run_scan_from_image(image: np.ndarray, scan_id: str | None = None, metadata: dict | None = None) -> dict:
    started = time.time()
    scan_id = scan_id or uuid.uuid4().hex[:8]
    metadata = metadata or {}
    work_dir = None
    try:
        results = detect_products(image)
        boxes = get_boxes(results)
        if not boxes:
            raise ValueError("No products detected in this shelf image.")

        records, work_dir = crop_products(image, boxes)
        classified = classify_records(records, scan_id=scan_id)
        inventory = aggregate_inventory(classified)
        products = inventory_to_api_products(inventory)
        processing_ms = int((time.time() - started) * 1000)
        metrics = compute_metrics(inventory, classified, image.shape, processing_ms)
        shares = brand_share(inventory)
        categories = category_breakdown(inventory)
        alerts = build_alerts(metrics)
        recommendations = build_recommendations(metrics, inventory)
        summary_text = executive_summary(metrics)

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
            executive_summary=summary_text,
            logo_path=LOGO_PATH if LOGO_PATH.exists() else None,
        )
        csv_b64 = base64.b64encode(generate_csv_bytes(inventory)).decode("utf-8")

        return {
            "scan_id": scan_id,
            "model_version": "yolov8+faiss+clip+gpt",
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
            "recommendations": recommendations,
            "annotated_image_base64": annotated_b64,
            "pdf_base64": pdf_b64,
            "csv_base64": csv_b64,
            "learned_updates": learned_updates,
            "learned_catalog_size": count_learned(),
            "learned_new_this_scan": len(learned_updates),
            "shelf_label": metadata.get("shelf_label"),
            "category": metadata.get("category"),
        }
    finally:
        if work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def run_scan_from_bytes(data: bytes, **kwargs) -> dict:
    return run_scan_from_image(load_image_bytes(data), **kwargs)


def run_scan_from_url(url: str, **kwargs) -> dict:
    return run_scan_from_image(load_image_from_url(url), **kwargs)
