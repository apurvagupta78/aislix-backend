"""PDF, CSV, and annotated image generation."""

from __future__ import annotations

import base64
import csv
import io
import uuid
from datetime import datetime

import cv2
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_annotated_image(image: np.ndarray, classified: list[dict]) -> np.ndarray:
    annotated = image.copy()
    for item in classified:
        x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]
        label = (item.get("brand") or "?")[:18]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 180, 0), 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(y1 - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 180, 0),
            1,
            cv2.LINE_AA,
        )
    return annotated


def generate_csv_bytes(inventory: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["brand", "product_name", "variant", "quantity", "confidence", "category", "stock_status"],
    )
    writer.writeheader()
    for row in inventory:
        writer.writerow(
            {
                "brand": row.get("brand", ""),
                "product_name": row.get("product_name", ""),
                "variant": row.get("variant", ""),
                "quantity": row.get("quantity", 0),
                "confidence": row.get("confidence", 0),
                "category": row.get("category", ""),
                "stock_status": row.get("stock_status", ""),
            }
        )
    return buffer.getvalue().encode("utf-8")


def _logo_flowable(logo_path, width=1.85 * inch):
    reader = ImageReader(str(logo_path))
    img_w, img_h = reader.getSize()
    if not img_w or not img_h:
        return RLImage(str(logo_path), width=width, height=0.5 * inch)
    height = width * (img_h / float(img_w))
    return RLImage(str(logo_path), width=width, height=height)


def generate_pdf_bytes(
    scan_id: str,
    metrics: dict,
    inventory: list[dict],
    shares: list[dict],
    recommendations: list[dict],
    alerts: list[dict] | None = None,
    executive_summary: str | None = None,
    logo_path=None,
) -> str:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    alerts = alerts or []

    if logo_path and logo_path.exists():
        story.append(_logo_flowable(logo_path))
        story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("<b>Aislix AI Shelf Audit Report</b>", styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    now = datetime.now()
    story.append(Paragraph(f"<b>Scan ID:</b> {scan_id}", styles["Normal"]))
    story.append(Paragraph(f"<b>Date:</b> {now.strftime('%d-%m-%Y %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))

    if executive_summary:
        story.append(Paragraph(f"<b>Executive Summary</b>", styles["Heading3"]))
        story.append(Paragraph(executive_summary, styles["Normal"]))
        story.append(Spacer(1, 0.15 * inch))

    summary = [
        ["Metric", "Value"],
        ["Total Facings", metrics.get("total_products", 0)],
        ["Unique SKUs", metrics.get("unique_skus", 0)],
        ["Unique Brands", metrics.get("unique_brands", 0)],
        ["Low Stock SKUs", metrics.get("low_stock_products", 0)],
        ["Shelf Utilization %", metrics.get("shelf_utilization_percent", metrics.get("share_of_shelf_percent", 0))],
        ["On-Shelf Availability %", metrics.get("osa_percent", 0)],
        ["Average Confidence", f"{metrics.get('average_confidence', 0) * 100:.1f}%"],
        ["Shelf Health Score", metrics.get("shelf_health_score", 0)],
    ]
    table = Table(summary, colWidths=[2.8 * inch, 2.2 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#09283e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    if alerts:
        story.append(Paragraph("<b>Critical Alerts</b>", styles["Heading3"]))
        for alert in alerts[:8]:
            severity = (alert.get("severity") or "medium").upper()
            title = alert.get("title") or "Alert"
            detail = alert.get("detail") or ""
            line = f"<b>[{severity}]</b> {title}"
            if detail:
                line += f" — {detail}"
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

    if shares:
        story.append(Paragraph("<b>Top Brands by Shelf Share</b>", styles["Heading3"]))
        brand_rows = [["Brand", "Share %"]] + [
            [row["brand"], f"{row['share']:.1f}"] for row in shares[:10]
        ]
        brand_table = Table(brand_rows, colWidths=[3 * inch, 1.5 * inch])
        brand_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.append(brand_table)
        story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>Complete Inventory</b>", styles["Heading3"]))
    inv_rows = [["Brand", "Product", "Variant", "Qty", "Conf.", "Stock"]] + [
        [
            row.get("brand", ""),
            row.get("product_name", "")[:28],
            row.get("variant", "")[:18] or "—",
            str(row.get("quantity", 0)),
            f"{float(row.get('confidence', 0)) * 100:.0f}%",
            (row.get("stock_status") or "in_stock").replace("_", " "),
        ]
        for row in inventory
    ]
    inv_table = Table(inv_rows, colWidths=[0.95 * inch, 1.45 * inch, 0.95 * inch, 0.45 * inch, 0.55 * inch, 0.75 * inch])
    inv_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(inv_table)

    if recommendations:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("<b>Recommendations</b>", styles["Heading3"]))
        for rec in recommendations[:8]:
            title = rec.get("title") or "Recommendation"
            detail = rec.get("detail") or ""
            impact = rec.get("impact") or ""
            suffix = f" ({impact} impact)" if impact else ""
            story.append(Paragraph(f"• <b>{title}</b>{suffix}", styles["Normal"]))
            if detail:
                story.append(Paragraph(f"&nbsp;&nbsp;{detail}", styles["Normal"]))

    doc.build(story)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_pdf(products, output_path="audit_report.pdf"):
    """Backward-compatible helper."""
    inventory = products
    metrics = {
        "total_products": sum(row.get("quantity", 1) for row in products),
        "unique_skus": len({row.get("product_name") for row in products}),
        "unique_brands": len({row.get("brand") for row in products}),
        "low_stock_products": 0,
        "share_of_shelf_percent": 0,
        "average_confidence": 0,
        "shelf_health_score": 0,
    }
    pdf_b64 = generate_pdf_bytes(str(uuid.uuid4())[:8], metrics, inventory, [], [], [], None, None)
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(pdf_b64))
    return output_path
