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
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.scan_context import COMPLIANCE_ALERT_INTERPRETATION, COMPLIANCE_ALERT_TITLE

MISMATCH_BOX_COLOR = (0, 0, 220)
OK_BOX_COLOR = (0, 210, 0)

# Fixed slot in the PDF summary — keeps page 1 layout stable for portrait shelf photos.
PDF_PAGE_MARGIN = 0.75 * inch
PDF_SUMMARY_IMAGE_WIDTH = 6.0 * inch
PDF_SUMMARY_IMAGE_MAX_HEIGHT = 3.25 * inch


import unicodedata


def _ascii_label(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").strip()


def _short_product_name(product: str) -> str:
    """Compact flavor label for small bounding boxes on chip facings."""
    p = (product or "").lower()
    if "magic masala" in p:
        return "Magic Masala"
    if "tomato tango" in p:
        return "Tomato Tango"
    if "cream" in p and "onion" in p:
        return "Cream & Onion"
    if "classic salted" in p:
        return "Classic Salted"
    words = (product or "").split()
    return " ".join(words[:3]) if words else ""


def _annotation_label(item: dict, img_w: int | None = None) -> str:
    brand = _ascii_label((item.get("brand") or "?").strip())
    product = _ascii_label((item.get("product_name") or "").strip())
    variant = _ascii_label((item.get("variant") or "").strip())
    short_product = _short_product_name(product)
    generic_products = {
        "toothpaste",
        "potato chips",
        "shampoo",
        "conditioner",
        "soap",
        "water bottle",
        "dishwashing liquid",
        "mouthwash",
        "unknown",
    }
    if variant and (
        product.lower() in generic_products
        or variant.lower() not in product.lower()
    ):
        short_product = _short_product_name(variant) or variant
    skip_product = product.lower() in {"", "unknown", "unidentified sku", brand.lower()}
    box_w = int(item.get("x2", 0)) - int(item.get("x1", 0))
    near_edge = img_w is not None and int(item.get("x2", 0)) >= img_w - 12
    max_len = 28 if (box_w < 90 or near_edge) else 44
    if item.get("subcategory_match") is False:
        prefix = "WRONG: "
        budget = max_len - len(prefix)
        return f"{prefix}{brand[:max(budget, 8)]}"
    qty = item.get("annotation_qty")
    qty_suffix = f" ({int(qty)})" if qty not in (None, "", 0) else ""
    if short_product and not skip_product:
        if box_w < 80 or near_edge:
            label = f"{short_product}{qty_suffix}"
            return label[:max_len]
        label = f"{brand} - {short_product}{qty_suffix}"
        return label[:max_len]
    if qty_suffix:
        return f"{brand}{qty_suffix}"[:max_len]
    return brand[:max_len]


def generate_annotated_image(
    image: np.ndarray,
    classified: list[dict],
    *,
    draw_labels: bool = True,
) -> np.ndarray:
    annotated = image.copy()
    img_h, img_w = annotated.shape[:2]
    base_scale = max(0.5, min(img_h, img_w) / 1600.0 * 0.6)

    for item in classified:
        x1, y1, x2, y2 = int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"])
        box_h = max(y2 - y1, 1)
        font_scale = max(0.45, min(0.9, base_scale * (box_h / 70.0)))
        thickness = max(1, int(round(font_scale * 2.2)))
        line_w = max(2, thickness)

        is_mismatch = item.get("subcategory_match") is False
        box_color = MISMATCH_BOX_COLOR if is_mismatch else OK_BOX_COLOR
        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, line_w)

        if not draw_labels:
            continue

        label = _annotation_label(item, img_w=img_w)
        (text_w, text_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        pad = 4
        label_h = text_h + baseline + pad * 2
        band_overlay = "band" in (item.get("recognition_source") or "")

        if band_overlay:
            bg_y1 = min(y1 + pad, max(y1, y2 - label_h - pad))
            bg_y2 = min(img_h - 1, bg_y1 + label_h)
            text_y = bg_y1 + text_h + pad
        elif y1 - label_h >= 0:
            bg_y1, bg_y2 = y1 - label_h, y1
            text_y = y1 - pad - baseline
        else:
            bg_y1, bg_y2 = y1, min(img_h - 1, y1 + label_h)
            text_y = y1 + text_h + pad

        bg_x1 = max(0, x1)
        bg_x2 = min(img_w - 1, bg_x1 + text_w + pad * 2)
        cv2.rectangle(annotated, (bg_x1, bg_y1), (bg_x2, bg_y2), (0, 0, 0), -1)
        cv2.putText(
            annotated,
            label,
            (bg_x1 + pad, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
    return annotated


def encode_shelf_image_bytes(image: np.ndarray, *, quality: int = 92) -> bytes:
    """Encode the original shelf photo as JPEG (no boxes) — same color path as annotated output."""
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    ok, encoded = cv2.imencode(".jpg", rgb, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("Could not encode shelf image.")
    return encoded.tobytes()


def encode_vision_image_bytes(
    image: np.ndarray,
    *,
    max_long_edge: int = 2048,
    quality: int = 85,
) -> bytes:
    """Downscale + compress shelf photo for OpenAI vision (API-only; originals unchanged)."""
    h, w = image.shape[:2]
    long_edge = max(h, w)
    if max_long_edge > 0 and long_edge > max_long_edge:
        scale = max_long_edge / float(long_edge)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return encode_shelf_image_bytes(image, quality=quality)


def encode_annotated_image_bytes(annotated: np.ndarray, *, quality: int = 92) -> bytes:
    """Encode annotated shelf image once — shared by download JPEG and PDF embed."""
    rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
    ok, encoded = cv2.imencode(".jpg", rgb, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("Could not encode annotated shelf image.")
    return encoded.tobytes()


def annotated_image_dimensions(annotated: np.ndarray) -> dict[str, int]:
    height, width = annotated.shape[:2]
    return {"width": int(width), "height": int(height)}


def _csv_escape(value) -> str:
    s = "" if value is None else str(value)
    if any(ch in s for ch in '",\n'):
        return f'"{s.replace(chr(34), chr(34) + chr(34))}"'
    return s


def _csv_section(title: str, rows: list[list]) -> list[str]:
    lines = [f"# {title}"]
    for row in rows:
        lines.append(",".join(_csv_escape(cell) for cell in row))
    return lines


def generate_csv_bytes(
    inventory: list[dict],
    *,
    scan_id: str | None = None,
    metrics: dict | None = None,
    shares: list[dict] | None = None,
    recommendations: list[dict] | None = None,
    alerts: list[dict] | None = None,
    compliance_alerts: list[dict] | None = None,
    executive_summary: str | None = None,
) -> bytes:
    """Inventory-only CSV when metrics is omitted; full multi-section report otherwise."""
    if not metrics:
        buffer = io.StringIO()
        fieldnames = [
            "Brand",
            "Product",
            "Variant",
            "Shelf Position",
            "Category",
            "Quantity",
            "Confidence %",
            "Compliance Alert",
            "Compliance Note",
            "Detected Sub-category",
            "Audit Sub-category",
            "Stock Status",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in inventory:
            conf = float(row.get("confidence") or 0)
            writer.writerow(
                {
                    "Brand": row.get("brand", ""),
                    "Product": row.get("product_name", ""),
                    "Variant": row.get("variant", ""),
                    "Shelf Position": row.get("shelf_position") or row.get("location") or "",
                    "Category": row.get("category", ""),
                    "Quantity": row.get("quantity", 0),
                    "Confidence %": round(conf * 100, 1),
                    "Compliance Alert": row.get("compliance_alert") or "OK",
                    "Compliance Note": row.get("compliance_interpretation") or "",
                    "Detected Sub-category": row.get("detected_sub_category_label") or "",
                    "Audit Sub-category": row.get("expected_sub_category_label") or "",
                    "Stock Status": (row.get("stock_status") or "in_stock").replace("_", " "),
                }
            )
        return buffer.getvalue().encode("utf-8")

    lines: list[str] = [
        "# Aislix Shelf Audit Report",
        f"# Scan ID,{_csv_escape(scan_id or '')}",
    ]
    execution = metrics.get("shelf_execution_score") or metrics.get("shelf_health_score") or 0
    lines.extend(
        _csv_section(
            "Execution summary",
            [
                ["Metric", "Value"],
                ["Shelf execution score", execution],
                ["Shelf health score", metrics.get("shelf_health_score", "")],
                ["Total facings", metrics.get("total_facings") or metrics.get("total_products", 0)],
                ["Unique SKUs", metrics.get("unique_skus", 0)],
                ["Unique brands", metrics.get("unique_brands", 0)],
                ["Recognition coverage %", metrics.get("recognition_coverage_percent", "")],
                ["Availability %", metrics.get("availability_percent") or metrics.get("osa_percent", "")],
                ["Facing compliance %", metrics.get("facing_compliance_percent", "")],
                ["Placement compliance %", metrics.get("placement_compliance_percent", "")],
                ["Share of shelf %", metrics.get("share_of_shelf_percent", "")],
                [
                    "Planogram compliance %",
                    metrics.get("planogram_sku_match_percent")
                    or metrics.get("planogram_compliance_percent", ""),
                ],
                ["Confirmed OOS", metrics.get("confirmed_oos_count") or metrics.get("out_of_stock_products", 0)],
                ["Possible OOS / low stock", metrics.get("possible_oos_count") or metrics.get("low_stock_products", 0)],
                ["Placement issues", metrics.get("placement_issue_count") or metrics.get("misplaced_products", 0)],
                ["Avg confidence %", round(float(metrics.get("average_confidence") or 0) * 100, 1)],
            ],
        )
    )
    if executive_summary:
        lines.extend(["", "# Executive summary", _csv_escape(executive_summary)])

    financial = metrics.get("financial_impact") or {}
    if financial:
        lines.extend(
            _csv_section(
                "Financial impact (indicative)",
                [
                    ["Metric", "Value (INR)"],
                    ["Estimated daily lost sales", financial.get("estimated_daily_lost_sales_inr", 0)],
                    ["Estimated weekly lost sales", financial.get("estimated_weekly_lost_sales_inr", 0)],
                    ["Estimated monthly lost sales", financial.get("estimated_monthly_lost_sales_inr", 0)],
                    ["OOS SKU count", financial.get("oos_sku_count", 0)],
                    ["At-risk SKU count", financial.get("at_risk_sku_count", 0)],
                    ["Confidence", financial.get("confidence", "")],
                    ["Methodology", financial.get("methodology", "")],
                ],
            )
        )

    if shares:
        lines.extend(
            _csv_section(
                "Top brands by shelf share",
                [["Brand", "Share %"]] + [[row.get("brand", ""), f"{float(row.get('share', 0)):.1f}"] for row in shares[:15]],
            )
        )

    if recommendations:
        lines.extend(
            _csv_section(
                "Recommended actions",
                [["Title", "Impact", "Detail"]]
                + [[rec.get("title", ""), rec.get("impact", ""), rec.get("detail", "")] for rec in recommendations[:20]],
            )
        )

    if compliance_alerts:
        lines.extend(
            _csv_section(
                "Compliance alerts",
                [["Severity", "Title", "Detail"]]
                + [[a.get("severity", ""), a.get("title", ""), a.get("detail", "")] for a in compliance_alerts[:20]],
            )
        )

    if alerts:
        lines.extend(
            _csv_section(
                "Alerts",
                [["Severity", "Title", "Detail"]]
                + [[a.get("severity", ""), a.get("title", ""), a.get("detail", "")] for a in alerts[:20]],
            )
        )

    inv_buffer = io.StringIO()
    fieldnames = [
        "Brand",
        "Product",
        "Variant",
        "Shelf Position",
        "Category",
        "Quantity",
        "Confidence %",
        "Compliance Alert",
        "Compliance Note",
        "Detected Sub-category",
        "Audit Sub-category",
        "Stock Status",
    ]
    writer = csv.DictWriter(inv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in inventory:
        conf = float(row.get("confidence") or 0)
        writer.writerow(
            {
                "Brand": row.get("brand", ""),
                "Product": row.get("product_name", ""),
                "Variant": row.get("variant", ""),
                "Shelf Position": row.get("shelf_position") or row.get("location") or "",
                "Category": row.get("category", ""),
                "Quantity": row.get("quantity", 0),
                "Confidence %": round(conf * 100, 1),
                "Compliance Alert": row.get("compliance_alert") or "OK",
                "Compliance Note": row.get("compliance_interpretation") or "",
                "Detected Sub-category": row.get("detected_sub_category_label") or "",
                "Audit Sub-category": row.get("expected_sub_category_label") or "",
                "Stock Status": (row.get("stock_status") or "in_stock").replace("_", " "),
            }
        )
    lines.extend(["", "# Complete inventory", inv_buffer.getvalue()])
    return "\n".join(lines).encode("utf-8")


def _logo_flowable(logo_path, width=1.85 * inch):
    reader = ImageReader(str(logo_path))
    img_w, img_h = reader.getSize()
    if not img_w or not img_h:
        return RLImage(str(logo_path), width=width, height=0.5 * inch)
    height = width * (img_h / float(img_w))
    return RLImage(str(logo_path), width=width, height=height)


def _fit_image_size(
    img_w: float,
    img_h: float,
    *,
    max_width: float,
    max_height: float,
) -> tuple[float, float]:
    if not img_w or not img_h:
        raise ValueError("Annotated shelf image has invalid dimensions.")
    scale = min(max_width / img_w, max_height / img_h)
    return img_w * scale, img_h * scale


def _annotated_image_flowable(
    jpeg_bytes: bytes,
    *,
    max_width: float = PDF_SUMMARY_IMAGE_WIDTH,
    max_height: float = PDF_SUMMARY_IMAGE_MAX_HEIGHT,
):
    """Embed annotated JPEG scaled to a fixed summary slot (aspect ratio preserved)."""
    bio = io.BytesIO(jpeg_bytes)
    reader = ImageReader(bio)
    img_w, img_h = reader.getSize()
    width, height = _fit_image_size(img_w, img_h, max_width=max_width, max_height=max_height)
    bio.seek(0)
    return RLImage(bio, width=width, height=height)


def _append_annotated_shelf_section(story: list, styles, annotated_jpeg: bytes) -> None:
    """Insert annotated shelf image in the summary section (same JPEG as scan result download)."""
    section = [
        Paragraph("<b>Annotated Shelf Image</b>", styles["Heading3"]),
        Paragraph(
            "<i>Detections rendered by the vision model (green = OK, red = mismatch).</i>",
            styles["Normal"],
        ),
        Spacer(1, 0.08 * inch),
        _annotated_image_flowable(annotated_jpeg),
    ]
    story.append(KeepTogether(section))
    story.append(Spacer(1, 0.2 * inch))


def generate_pdf_bytes(
    scan_id: str,
    metrics: dict,
    inventory: list[dict],
    shares: list[dict],
    recommendations: list[dict],
    alerts: list[dict] | None = None,
    compliance_alerts: list[dict] | None = None,
    subcategory_mismatches: list[dict] | None = None,
    executive_summary: str | None = None,
    logo_path=None,
    annotated_jpeg: bytes | None = None,
    annotated_image: np.ndarray | None = None,
) -> str:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_PAGE_MARGIN,
        rightMargin=PDF_PAGE_MARGIN,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    styles = getSampleStyleSheet()
    story = []
    alerts = alerts or []
    compliance_alerts = compliance_alerts or []
    subcategory_mismatches = subcategory_mismatches or []

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

    if annotated_jpeg is None and annotated_image is not None and annotated_image.size > 0:
        annotated_jpeg = encode_annotated_image_bytes(annotated_image)

    if annotated_jpeg:
        _append_annotated_shelf_section(story, styles, annotated_jpeg)

    execution_score = metrics.get("shelf_execution_score") or metrics.get("shelf_health_score") or 0
    summary = [
        ["Metric", "Value"],
        ["Shelf Execution Score", execution_score],
        ["Shelf Health Score", metrics.get("shelf_health_score", 0)],
        ["Total Facings", metrics.get("total_facings") or metrics.get("total_products", 0)],
        ["Unique SKUs", metrics.get("unique_skus", 0)],
        ["Unique Brands", metrics.get("unique_brands", 0)],
        ["Recognition Coverage %", metrics.get("recognition_coverage_percent", 0)],
        ["On-Shelf Availability %", metrics.get("availability_percent") or metrics.get("osa_percent", 0)],
        ["Facing Compliance %", metrics.get("facing_compliance_percent", 0)],
        ["Placement Compliance %", metrics.get("placement_compliance_percent", 0)],
        ["Planogram Compliance %", metrics.get("planogram_sku_match_percent") or metrics.get("planogram_compliance_percent", 0)],
        ["Share of Shelf %", metrics.get("share_of_shelf_percent", metrics.get("shelf_utilization_percent", 0))],
        ["Low Stock SKUs", metrics.get("low_stock_products", 0)],
        ["Possible OOS / Low Stock", metrics.get("possible_oos_count", 0)],
        ["Misplaced / Wrong Sub-category", metrics.get("misplaced_products", 0)],
        ["Average Confidence", f"{metrics.get('average_confidence', 0) * 100:.1f}%"],
    ]
    financial = metrics.get("financial_impact") or {}
    if financial:
        summary.extend(
            [
                ["Est. Daily Lost Sales (INR)", financial.get("estimated_daily_lost_sales_inr", 0)],
                ["Est. Weekly Lost Sales (INR)", financial.get("estimated_weekly_lost_sales_inr", 0)],
                ["OOS SKU Count", financial.get("oos_sku_count", 0)],
                ["At-Risk SKU Count", financial.get("at_risk_sku_count", 0)],
            ]
        )
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

    if compliance_alerts:
        story.append(Paragraph(f"<b>{COMPLIANCE_ALERT_TITLE}</b>", styles["Heading3"]))
        story.append(
            Paragraph(
                f"<i>{COMPLIANCE_ALERT_INTERPRETATION}</i>",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.08 * inch))
        for alert in compliance_alerts[:8]:
            severity = (alert.get("severity") or "medium").upper()
            detail = alert.get("detail") or ""
            line = f"<b>[{severity}]</b> {alert.get('title') or COMPLIANCE_ALERT_TITLE}"
            if detail:
                line += f" — {detail}"
            story.append(Paragraph(line, styles["Normal"]))
        if subcategory_mismatches:
            story.append(Spacer(1, 0.1 * inch))
            mismatch_rows = [["Brand", "Product", "Detected", "Expected", "Qty"]] + [
                [
                    row.get("brand", ""),
                    (row.get("product_name") or "")[:24],
                    row.get("detected_sub_category_label", ""),
                    row.get("expected_sub_category_label", ""),
                    str(row.get("quantity", 0)),
                ]
                for row in subcategory_mismatches[:12]
            ]
            mismatch_table = Table(
                mismatch_rows,
                colWidths=[0.85 * inch, 1.35 * inch, 0.85 * inch, 0.85 * inch, 0.4 * inch],
            )
            mismatch_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
            story.append(mismatch_table)
        story.append(Spacer(1, 0.2 * inch))

    other_alerts = [a for a in alerts if a.get("category") != "compliance"]
    if other_alerts:
        story.append(Paragraph("<b>Critical Alerts</b>", styles["Heading3"]))
        for alert in other_alerts[:8]:
            severity = (alert.get("severity") or "medium").upper()
            title = alert.get("title") or "Alert"
            detail = alert.get("detail") or ""
            line = f"<b>[{severity}]</b> {title}"
            if detail:
                line += f" — {detail}"
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))
    elif alerts and not compliance_alerts:
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
    inv_rows = [["Brand", "Product", "Variant", "Qty", "Conf.", "Compliance"]] + [
        [
            row.get("brand", ""),
            row.get("product_name", "")[:28],
            row.get("variant", "")[:18] or "—",
            str(row.get("quantity", 0)),
            f"{float(row.get('confidence', 0)) * 100:.0f}%",
            (
                COMPLIANCE_ALERT_TITLE
                if row.get("compliance_status") == "category_mismatch"
                else "OK"
            ),
        ]
        for row in inventory
    ]
    inv_table = Table(inv_rows, colWidths=[0.85 * inch, 1.35 * inch, 0.85 * inch, 0.45 * inch, 0.55 * inch, 1.0 * inch])
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
