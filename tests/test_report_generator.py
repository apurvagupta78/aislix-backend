"""Tests for PDF and annotated image report generation."""

from __future__ import annotations

import base64

import cv2
import numpy as np

from app.report_generator import (
    PDF_CONTENT_WIDTH,
    PDF_SUMMARY_IMAGE_MAX_HEIGHT,
    PDF_SUMMARY_IMAGE_WIDTH,
    REPORT_TITLE,
    _annotation_label,
    _executive_summary_flowables,
    _fit_image_size,
    _scale_col_widths,
    build_report_context,
    encode_annotated_image_bytes,
    encode_shelf_image_bytes,
    generate_annotated_image,
    generate_csv_bytes,
    generate_pdf_bytes,
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph


def test_generate_annotated_image_boxes_only():
    image = np.zeros((200, 300, 3), dtype=np.uint8)
    classified = [
        {
            "x1": 20,
            "y1": 30,
            "x2": 80,
            "y2": 90,
            "brand": "Lays",
            "product_name": "Potato Chips",
            "variant": "Magic Masala",
        }
    ]
    annotated = generate_annotated_image(image, classified, draw_labels=False)
    assert annotated.shape == image.shape
    assert not np.array_equal(annotated, image)


def test_annotation_uses_short_flavor_on_small_boxes():
    label = _annotation_label(
        {
            "brand": "Lays",
            "product_name": "Indias Magic Masala Potato Chips",
            "x1": 0,
            "x2": 70,
            "y1": 0,
            "y2": 100,
        },
        img_w=400,
    )
    assert label == "Magic Masala"


def test_annotation_uses_variant_when_product_is_generic():
    label = _annotation_label(
        {
            "brand": "Colgate",
            "product_name": "Toothpaste",
            "variant": "Triple Accion",
            "x1": 0,
            "x2": 200,
            "y1": 0,
            "y2": 100,
        },
        img_w=800,
    )
    assert "Triple Accion" in label
    assert "Toothpaste" not in label or "Colgate" in label


def test_original_and_annotated_share_dimensions():
    image = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
    classified = [
        {
            "brand": "Lays",
            "product_name": "Tomato Tango Potato Chips",
            "x1": 10,
            "y1": 10,
            "x2": 80,
            "y2": 120,
        }
    ]
    original = encode_shelf_image_bytes(image)
    annotated = encode_annotated_image_bytes(generate_annotated_image(image, classified))
    assert original[:2] == b"\xff\xd8"
    assert annotated[:2] == b"\xff\xd8"
    assert len(original) > 1000
    assert len(annotated) > 1000


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


def test_pdf_annotated_image_after_executive_summary():
    """Annotated JPEG is embedded in summary section (same bytes as download)."""
    image = np.full((120, 160, 3), 200, dtype=np.uint8)
    classified = [
        {
            "brand": "Lipton",
            "product_name": "Green Tea",
            "confidence": 0.9,
            "x1": 10,
            "y1": 10,
            "x2": 80,
            "y2": 90,
        }
    ]
    jpeg_bytes = encode_annotated_image_bytes(generate_annotated_image(image, classified))
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
    pdf_without_image = base64.b64decode(
        generate_pdf_bytes(
            "scan-order-test",
            metrics,
            [],
            [],
            [],
            executive_summary="Shelf audit completed with one facing detected.",
            annotated_jpeg=None,
        )
    )
    pdf_with_image = base64.b64decode(
        generate_pdf_bytes(
            "scan-order-test",
            metrics,
            [{"brand": "Lipton", "product_name": "Green Tea", "quantity": 1, "confidence": 0.9}],
            [],
            [],
            executive_summary="Shelf audit completed with one facing detected.",
            annotated_jpeg=jpeg_bytes,
        )
    )
    assert pdf_with_image.startswith(b"%PDF")
    assert len(pdf_with_image) > len(pdf_without_image) + 5000


def test_pdf_summary_image_fits_fixed_slot():
    """Portrait shelf JPEG scales down into the PDF summary box without upscaling."""
    width, height = _fit_image_size(
        1200,
        1600,
        max_width=PDF_SUMMARY_IMAGE_WIDTH,
        max_height=PDF_SUMMARY_IMAGE_MAX_HEIGHT,
    )
    assert width <= PDF_SUMMARY_IMAGE_WIDTH + 0.01
    assert height <= PDF_SUMMARY_IMAGE_MAX_HEIGHT + 0.01
    assert width < PDF_SUMMARY_IMAGE_WIDTH
    assert height == PDF_SUMMARY_IMAGE_MAX_HEIGHT

    landscape_w, landscape_h = _fit_image_size(
        2000,
        900,
        max_width=PDF_SUMMARY_IMAGE_WIDTH,
        max_height=PDF_SUMMARY_IMAGE_MAX_HEIGHT,
    )
    assert landscape_w == PDF_SUMMARY_IMAGE_WIDTH
    assert landscape_h < PDF_SUMMARY_IMAGE_MAX_HEIGHT


def test_csv_eight_section_structure():
    metrics = {
        "total_facings": 12,
        "unique_skus": 4,
        "unique_brands": 3,
        "recognition_coverage_percent": 88.0,
        "shelf_execution_score": 72.0,
        "average_confidence": 0.86,
    }
    inventory = [
        {
            "brand": "Colgate",
            "product_name": "MaxFresh",
            "quantity": 3,
            "confidence": 0.9,
            "x1": 10,
            "y1": 20,
            "x2": 80,
            "y2": 120,
            "recognition_source": "vision",
        }
    ]
    ctx = build_report_context(
        scan_id="scan-abc",
        metrics=metrics,
        location="A-1",
        category="Personal Care",
        sub_category="Toothpaste",
    )
    csv_text = generate_csv_bytes(
        inventory,
        scan_id="scan-abc",
        metrics=metrics,
        shares=[{"brand": "Colgate", "share": 40.0}],
        recommendations=[{"title": "Refill gap", "impact": "high", "detail": "Restock shelf"}],
        executive_summary="Toothpaste bay audited.",
        report_context=ctx,
    ).decode("utf-8")
    assert REPORT_TITLE in csv_text
    assert "Section 1" in csv_text
    assert "Section 8" in csv_text
    assert "PHOTO-DETECTED" in csv_text
    assert "Colgate" in csv_text


def test_pdf_eight_section_header():
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
        "total_facings": 1,
    }
    ctx = build_report_context(scan_id="scan-pdf-8", metrics=metrics, location="B-2")
    pdf = base64.b64decode(
        generate_pdf_bytes(
            "scan-pdf-8",
            metrics,
            [{"brand": "Lipton", "product_name": "Green Tea", "quantity": 1, "confidence": 0.9}],
            [],
            [],
            executive_summary="Test summary.",
            report_context=ctx,
        )
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000


def test_executive_summary_strips_markdown_headings_to_bold_bullets():
    styles = getSampleStyleSheet()
    body = styles["Normal"]
    heading = styles["Normal"]
    text = "## Audit Overview\nShelf looks healthy.\n## Risks\n- Gap on endcap\nSecond issue line"
    flowables = _executive_summary_flowables(text, heading_style=heading, body_style=body)
    rendered = [getattr(f, "text", "") for f in flowables if isinstance(f, Paragraph)]
    joined = "\n".join(rendered)
    assert "##" not in joined
    assert "<b>Audit Overview</b>" in joined
    assert "<b>Risks</b>" in joined
    assert "• Shelf looks healthy." in joined
    assert "• Gap on endcap" in joined
    assert "• Second issue line" in joined


def test_pdf_col_widths_never_exceed_content_width():
    widths = _scale_col_widths(
        [0.6 * inch, 0.9 * inch, 0.55 * inch, 0.35 * inch, 0.4 * inch, 0.7 * inch, 0.75 * inch, 0.5 * inch, 0.55 * inch],
        9,
    )
    assert abs(sum(widths) - float(PDF_CONTENT_WIDTH)) < 0.5


def test_pdf_with_wide_section_tables_builds():
    """Sections 4/5/5b/6/8 with dense rows must still produce a valid PDF."""
    metrics = {
        "total_products": 3,
        "unique_skus": 3,
        "unique_brands": 2,
        "low_stock_products": 0,
        "misplaced_products": 0,
        "shelf_utilization_percent": 50.0,
        "osa_percent": 100.0,
        "average_confidence": 0.9,
        "shelf_health_score": 85.0,
        "total_facings": 3,
        "financial_impact": {
            "estimated_daily_lost_sales_inr": 120,
            "estimated_weekly_lost_sales_inr": 840,
            "oos_sku_count": 1,
            "at_risk_sku_count": 1,
            "confidence": "medium",
            "methodology": "units × price",
        },
        "planogram_compliance": {
            "lines": [
                {
                    "expected_brand": "Colgate",
                    "expected_product": "MaxFresh",
                    "actual_brand": "Pepsodent",
                    "actual_product": "Germin-Check",
                    "issue_type": "wrong_product",
                    "severity": "high",
                    "detail": "Facing mismatch on bay A-1",
                }
            ]
        },
    }
    inventory = [
        {
            "brand": "Colgate",
            "product_name": "MaxFresh Blue Gel Toothpaste Long Name",
            "variant": "100g",
            "quantity": 2,
            "confidence": 0.91,
            "x1": 10,
            "y1": 20,
            "x2": 80,
            "y2": 120,
            "recognition_source": "vision",
            "stock_status": "in_stock",
        }
        for _ in range(12)
    ]
    summary = (
        "## Audit Overview\nToothpaste bay audited with planogram.\n"
        "## Executive Findings\n- Share gap on Colgate\n- Extra Pepsodent facing"
    )
    pdf = base64.b64decode(
        generate_pdf_bytes(
            "scan-wide-tables",
            metrics,
            inventory,
            [{"brand": "Colgate", "share": 55.0}],
            [{"title": "Restock", "impact": "high", "detail": "Fill gap"}],
            executive_summary=summary,
            report_context=build_report_context(scan_id="scan-wide-tables", metrics=metrics),
        )
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 4000
