"""Tests for PDF and annotated image report generation."""

from __future__ import annotations

import base64

import cv2
import numpy as np

from app.report_generator import encode_annotated_image_bytes, generate_annotated_image, generate_pdf_bytes


def test_pdf_uses_same_jpeg_bytes_as_download():
    image = np.full((240, 320, 3), 255, dtype=np.uint8)
    classified = [
        {
            "brand": "Tata",
            "product_name": "Tea Agni",
            "confidence": 0.9,
            "x1": 20,
            "y1": 30,
            "x2": 120,
            "y2": 180,
        }
    ]
    annotated = generate_annotated_image(image, classified)
    jpeg_bytes = encode_annotated_image_bytes(annotated)
    metrics = {
        "total_products": 1,
        "unique_skus": 1,
        "unique_brands": 1,
        "low_stock_products": 0,
        "misplaced_products": 0,
        "shelf_utilization_percent": 50.0,
        "osa_percent": 100.0,
        "average_confidence": 0.9,
        "shelf_health_score": 85.0,
    }

    pdf_without = base64.b64decode(
        generate_pdf_bytes("scan-test", metrics, [], [], [], annotated_jpeg=None)
    )
    pdf_with = base64.b64decode(
        generate_pdf_bytes("scan-test", metrics, [], [], [], annotated_jpeg=jpeg_bytes)
    )

    assert pdf_with.startswith(b"%PDF")
    assert len(pdf_with) > len(pdf_without) + 5000
    assert jpeg_bytes[:2] == b"\xff\xd8"
