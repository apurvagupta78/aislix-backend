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
        fieldnames=["brand", "product_name", "variant", "quantity", "confidence", "category"],
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
            }
        )
    return buffer.getvalue().encode("utf-8")


def generate_pdf_bytes(
    scan_id: str,
    metrics: dict,
    inventory: list[dict],
    shares: list[dict],
    recommendations: list[dict],
    logo_path=None,
) -> str:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    if logo_path and logo_path.exists():
        story.append(RLImage(str(logo_path), width=1.6 * inch, height=0.55 * inch))
        story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("<b>Aislix AI Shelf Audit Report</b>", styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    now = datetime.now()
    story.append(Paragraph(f"<b>Scan ID:</b> {scan_id}", styles["Normal"]))
    story.append(Paragraph(f"<b>Date:</b> {now.strftime('%d-%m-%Y %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    summary = [
        ["Metric", "Value"],
        ["Total Products", metrics.get("total_products", 0)],
        ["Unique SKUs", metrics.get("unique_skus", 0)],
        ["Unique Brands", metrics.get("unique_brands", 0)],
        ["Low Stock Products", metrics.get("low_stock_products", 0)],
        ["Shelf Utilization %", metrics.get("share_of_shelf_percent", 0)],
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
    story.append(Spacer(1, 0.25 * inch))

    if shares:
        story.append(Paragraph("<b>Top Brands</b>", styles["Heading3"]))
        brand_rows = [["Brand", "Share %"]] + [
            [row["brand"], f"{row['share']:.1f}"] for row in shares[:10]
        ]
        brand_table = Table(brand_rows, colWidths=[3 * inch, 1.5 * inch])
        brand_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.append(brand_table)
        story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("<b>Inventory</b>", styles["Heading3"]))
    inv_rows = [["Brand", "Product", "Variant", "Qty", "Conf."]] + [
        [
            row.get("brand", ""),
            row.get("product_name", "")[:28],
            row.get("variant", "")[:18],
            str(row.get("quantity", 0)),
            f"{float(row.get('confidence', 0)) * 100:.0f}%",
        ]
        for row in inventory[:40]
    ]
    inv_table = Table(inv_rows, colWidths=[1.1 * inch, 1.5 * inch, 1.0 * inch, 0.5 * inch, 0.6 * inch])
    inv_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(inv_table)

    if recommendations:
        story.append(Spacer(1, 0.25 * inch))
        story.append(Paragraph("<b>Recommendations</b>", styles["Heading3"]))
        for rec in recommendations[:5]:
            story.append(Paragraph(f"• {rec.get('title', '')}", styles["Normal"]))

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
    pdf_b64 = generate_pdf_bytes(str(uuid.uuid4())[:8], metrics, inventory, [], [])
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(pdf_b64))
    return output_path
