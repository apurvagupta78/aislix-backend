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

REPORT_SPEC_VERSION = "1.0"
REPORT_TITLE = "RETAIL SHELF AI ANALYSIS REPORT"

_CAPTURE_LIMITATIONS = [
    "Single front-facing photos show visible facings only — not hidden depth, backroom stock, or store-wide inventory.",
    "Shelf absence in-frame is not confirmed inventory stockout without operational verification.",
    "Financial impact figures are indicative estimates when user-supplied prices and demand are configured.",
    "Linear shelf share and physical centimeters require calibration not available from photo alone.",
    "Execution score is withheld when assessed KPI coverage is below 80%.",
]

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


def _na(value) -> str:
    if value is None or value == "":
        return "N/A"
    return str(value)


def _metric_state(metrics: dict, key: str) -> str:
    retail = metrics.get("retail_execution_score") or {}
    if key == "shelf_execution_score" and retail.get("withhold_reason"):
        return "withheld"
    intel = metrics.get("retail_intelligence") or {}
    block = intel.get(key)
    if isinstance(block, dict) and block.get("state"):
        return str(block["state"])
    return "ready" if metrics.get(key) is not None else "not_configured"


def build_report_context(
    *,
    scan_id: str,
    metrics: dict | None = None,
    model_version: str | None = None,
    store_id: str | None = None,
    store_label: str | None = None,
    location: str | None = None,
    category: str | None = None,
    sub_category: str | None = None,
    customer_type: str | None = None,
    status: str = "DRAFT",
) -> dict:
    """Context block for eight-section exports — see docs/retail-shelf-ai-analysis-report-spec.md."""
    metrics = metrics or {}
    audit = metrics.get("audit_scope") or {}
    intel = metrics.get("retail_intelligence") or {}
    iq = intel.get("image_quality") or {}
    iq_score_block = iq.get("audit_image_quality_score") or {}
    iq_score = (
        iq_score_block.get("value")
        if isinstance(iq_score_block, dict)
        else iq_score_block
    )
    boundary_parts = [p for p in [category, sub_category, location] if p]
    enabled: list[str] = ["Photo detection", "Facing counts", "Brand share (scoped)"]
    omitted: list[str] = []
    if metrics.get("planogram_sku_match_percent") is not None or metrics.get("planogram_compliance_percent") is not None:
        enabled.append("Planogram compliance")
    else:
        omitted.append("Planogram compliance — no reference planogram")
    if metrics.get("financial_impact"):
        enabled.append("Financial impact (indicative)")
    else:
        omitted.append("Financial impact — prices/demand not configured")
    omitted.append("Linear shelf share — geometry not calibrated")
    omitted.append("POS/WMS inventory — Tier D not connected")
    recapture = "YES" if iq.get("rescan_recommended") or float(iq_score or 100) < 60 else "NO"
    return {
        "report_id": scan_id,
        "status": status,
        "spec_version": REPORT_SPEC_VERSION,
        "model_version": model_version or metrics.get("model_version") or "aislix-pipeline",
        "store_id": store_id,
        "store_label": store_label or store_id,
        "location": location,
        "category": category,
        "sub_category": sub_category,
        "customer_type": customer_type or "retail",
        "analysis_boundary": " · ".join(boundary_parts) if boundary_parts else "Photographed shelf area",
        "audit_scope": audit,
        "image_quality": iq,
        "recapture_required": recapture,
        "detection_mode": metrics.get("detection_mode") or "vision_pipeline",
        "enabled_modules": enabled,
        "omitted_modules": omitted,
    }


def _audit_kpi_pdf_rows(metrics: dict) -> list[list]:
    """Role-specific five KPI dashboard for PDF section 5a."""
    intel = metrics.get("retail_intelligence") or {}
    dashboard = intel.get("audit_kpi_dashboard") or {}
    kpis = dashboard.get("primary_kpis") or []
    if not kpis:
        return [["KPI", "Value", "Coverage", "Status", "Numerator", "Denominator"]]
    rows = [["KPI", "Value", "Coverage", "Status", "Numerator", "Denominator"]]
    for kpi in kpis[:5]:
        value = kpi.get("value")
        if kpi.get("unit") == "count" and value is not None:
            display = str(value)
            if kpi.get("denominator") is not None:
                display = f"{value} / {kpi.get('denominator')} planned"
        elif value is not None:
            display = f"{round(float(value), 1)}%"
        else:
            display = (kpi.get("status") or "n/a").replace("_", " ")
        cov = kpi.get("coverage_percent")
        rows.append(
            [
                _ascii_label(kpi.get("label") or kpi.get("kpi_id") or ""),
                display,
                f"{round(float(cov), 1)}%" if cov is not None else "—",
                _ascii_label(str(kpi.get("status") or "")),
                _na(kpi.get("numerator")),
                _na(kpi.get("denominator")),
            ]
        )
    return rows


def _price_exception_pdf_rows(metrics: dict) -> list[list]:
    intel = metrics.get("retail_intelligence") or {}
    pricing = intel.get("pricing") or {}
    lines = pricing.get("lines") if isinstance(pricing, dict) else []
    if not lines:
        return []
    rows = [["Product", "Expected INR", "Detected INR", "Variance", "Status"]]
    for line in lines[:20]:
        if not isinstance(line, dict):
            continue
        rows.append(
            [
                _ascii_label(f"{line.get('brand', '')} {line.get('product', '')}".strip())[:32],
                _na(line.get("expected_price_inr")),
                _na(line.get("detected_price_inr")),
                _na(line.get("variance_inr")),
                _ascii_label(str(line.get("status") or "")),
            ]
        )
    return rows


def _planogram_exception_pdf_rows(metrics: dict) -> list[list]:
    compliance = metrics.get("planogram_compliance") or {}
    lines = compliance.get("lines") if isinstance(compliance, dict) else []
    if not lines:
        return []
    rows = [["Expected", "Actual", "Issue", "Severity", "Detail"]]
    for line in lines[:25]:
        if not isinstance(line, dict):
            continue
        if line.get("issue_type") == "correct":
            continue
        rows.append(
            [
                _ascii_label(f"{line.get('expected_brand', '')} {line.get('expected_product', '')}".strip())[:28],
                _ascii_label(f"{line.get('actual_brand', '')} {line.get('actual_product', '')}".strip())[:28],
                _ascii_label(str(line.get("issue_type") or "")),
                _ascii_label(str(line.get("severity") or "")),
                _ascii_label(str(line.get("detail") or ""))[:40],
            ]
        )
    return rows


def _kpi_export_rows(metrics: dict) -> list[list]:
    """KPI rows: name, value, numerator, denominator, coverage, state, scope note."""
    scope = metrics.get("brand_share_scope") or metrics.get("brand_share_denominator") or ""
    denom_note = f"scope={scope}" if scope else ""
    retail = metrics.get("retail_execution_score") or {}
    exec_val = metrics.get("shelf_execution_score")
    if retail.get("withhold_reason"):
        exec_display = f"withheld ({retail['withhold_reason']})"
    else:
        exec_display = _na(exec_val)

    def row(name, value, num="", den="", cov="", state_key=""):
        return [
            name,
            _na(value),
            _na(num),
            _na(den),
            _na(cov),
            _metric_state(metrics, state_key) if state_key else "ready",
            denom_note if "share" in name.lower() else "",
        ]

    total_facings = metrics.get("total_facings") or metrics.get("total_products")
    rec_cov = metrics.get("recognition_coverage_percent")
    rows = [
        ["KPI", "Value", "Numerator", "Denominator", "Coverage", "State", "Scope"],
        row("Shelf execution score", exec_display, state_key="shelf_execution_score"),
        row("Visible facings", total_facings, total_facings, "assessed image", rec_cov),
        row("Unique SKUs", metrics.get("unique_skus"), metrics.get("unique_skus"), total_facings),
        row("Unique brands", metrics.get("unique_brands"), metrics.get("unique_brands"), total_facings),
        row("Recognition coverage %", rec_cov, "", "", rec_cov),
        row(
            "On-shelf availability %",
            metrics.get("availability_percent") or metrics.get("osa_percent"),
            "",
            "",
            "",
            "planogram_sku_match_percent",
        ),
        row("Facing compliance %", metrics.get("facing_compliance_percent")),
        row("Placement compliance %", metrics.get("placement_compliance_percent")),
        row(
            "Planogram compliance %",
            metrics.get("planogram_sku_match_percent") or metrics.get("planogram_compliance_percent"),
        ),
        row("Share of shelf %", metrics.get("share_of_shelf_percent")),
        row("Confirmed shelf absence count", metrics.get("confirmed_oos_count") or metrics.get("out_of_stock_products")),
        row("Low stock / suspected gaps", metrics.get("possible_oos_count") or metrics.get("low_stock_products")),
        row("Placement issues", metrics.get("placement_issue_count") or metrics.get("misplaced_products")),
        row("Avg confidence %", round(float(metrics.get("average_confidence") or 0) * 100, 1)),
    ]
    return rows


def _section1_rows(ctx: dict) -> list[list]:
    facility = (ctx.get("customer_type") or "retail").replace("_", " ").title()
    return [
        ["Field", "Value"],
        ["Business / site", _na(ctx.get("store_label") or ctx.get("store_id"))],
        ["Facility type", facility],
        ["Location", _na(ctx.get("location"))],
        ["Category / sub-category", _na(f"{ctx.get('category') or ''} / {ctx.get('sub_category') or ''}".strip(" /"))],
        ["Analysis boundary", _na(ctx.get("analysis_boundary"))],
    ]


def _append_executive_summary(story: list, styles, executive_summary: str | None) -> None:
    """Render executive summary as flowable Paragraphs — never inside a Table cell.

    ReportLab cannot split a single Table cell across pages; long Astra/Aislix
    summaries previously raised LayoutError and failed the entire scan.
    """
    text = _na(executive_summary).strip()
    if not text or text == "N/A":
        return
    from xml.sax.saxutils import escape

    # Soft cap keeps PDFs readable; full summary remains in the API/UI payload.
    if len(text) > 3500:
        text = text[:3500].rstrip() + "…"
    story.append(Paragraph("<b>Executive summary</b>", styles["Heading3"]))
    # Chunk so no single Paragraph exceeds roughly one page of body text.
    chunk_size = 1200
    for start in range(0, len(text), chunk_size):
        chunk = text[start : start + chunk_size]
        story.append(Paragraph(escape(chunk).replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 0.08 * inch))
    story.append(Spacer(1, 0.1 * inch))


def _image_quality_score(iq: dict) -> str:
    block = iq.get("audit_image_quality_score")
    if isinstance(block, dict):
        return _na(block.get("value"))
    return _na(block)


def _section2_rows(ctx: dict, metrics: dict) -> list[list]:
    iq = ctx.get("image_quality") or {}
    audit = ctx.get("audit_scope") or {}
    return [
        ["Field", "Value"],
        ["Photo reference", "Embedded annotated image (Section 8)"],
        ["Site ID", _na(ctx.get("store_id"))],
        ["Location ID", _na(ctx.get("location"))],
        ["Category scope", _na(ctx.get("category"))],
        ["Image quality score", _image_quality_score(iq)],
        ["Assessable facings in scope", _na(audit.get("in_scope_facings"))],
        ["Recapture required", _na(ctx.get("recapture_required"))],
        ["Detection mode", _na(ctx.get("detection_mode"))],
        ["Model / system version", _na(ctx.get("model_version"))],
        ["Evidence convention", "PHOTO-DETECTED unless marked USER-SUPPLIED"],
        ["Missing-data rule", "UNKNOWN/NOT ASSESSABLE — null is not zero"],
    ]


def _section3_rows(ctx: dict, metrics: dict) -> list[list]:
    audit = ctx.get("audit_scope") or {}
    return [
        ["Field", "Value"],
        ["Location hierarchy", f"Site > {ctx.get('location') or 'bay'} > {ctx.get('category') or 'category'}"],
        ["Coordinate system", "Normalized image bounding boxes"],
        ["In-scope facings", _na(audit.get("in_scope_facings"))],
        ["Adjacent bay exclusions", _na(audit.get("excluded_adjacent_facings"))],
        ["Planogram reference", "Configured" if metrics.get("planogram_sku_match_percent") is not None else "Not supplied"],
    ]


def _inventory_observation_rows(inventory: list[dict]) -> list[list]:
    header = [
        "Brand",
        "Product",
        "Variant",
        "Qty",
        "Conf %",
        "BBox",
        "Evidence",
        "Stock",
        "Compliance",
    ]
    rows = [header]
    for row in inventory[:200]:
        bbox = ""
        if row.get("x1") is not None:
            bbox = f"{row.get('x1')},{row.get('y1')}-{row.get('x2')},{row.get('y2')}"
        conf = float(row.get("confidence") or 0)
        conf_pct = round(conf * 100, 1) if conf <= 1 else round(conf, 1)
        evidence = "PHOTO-DETECTED"
        src = row.get("recognition_source")
        if src:
            evidence = f"PHOTO-DETECTED ({src})"
        compliance = "OK"
        if row.get("compliance_status") == "category_mismatch":
            compliance = COMPLIANCE_ALERT_TITLE
        rows.append(
            [
                row.get("brand", ""),
                row.get("product_name", ""),
                row.get("variant", "") or "—",
                str(row.get("quantity", 0)),
                conf_pct,
                bbox or "—",
                evidence,
                (row.get("stock_status") or "in_stock").replace("_", " "),
                compliance,
            ]
        )
    return rows


def _section6_rows(metrics: dict) -> list[list]:
    financial = metrics.get("financial_impact") or {}
    if not financial:
        return [["Note", "Commercial inventory KPIs not configured (Tier C/D inputs required)"]]
    return [
        ["Metric", "Value (INR)", "Evidence"],
        ["Est. daily lost sales", financial.get("estimated_daily_lost_sales_inr", 0), "ESTIMATED"],
        ["Est. weekly lost sales", financial.get("estimated_weekly_lost_sales_inr", 0), "ESTIMATED"],
        ["OOS SKU count", financial.get("oos_sku_count", 0), "PHOTO-DETECTED + USER-SUPPLIED"],
        ["At-risk SKU count", financial.get("at_risk_sku_count", 0), "PHOTO-DETECTED"],
        ["Confidence", financial.get("confidence", ""), ""],
        ["Methodology", financial.get("methodology", ""), ""],
    ]


def _action_rows(metrics: dict, recommendations: list[dict]) -> list[list]:
    intel = metrics.get("retail_intelligence") or {}
    ledger = intel.get("opportunity_ledger") or []
    rows = [["Priority", "Issue", "SKU/Brand", "Evidence", "Action", "Est. daily INR"]]
    for item in ledger[:15]:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("severity") or item.get("priority") or "medium",
                item.get("issue") or "",
                item.get("sku") or item.get("brand") or "",
                "PHOTO-DETECTED",
                item.get("recommended_action") or item.get("title") or "",
                item.get("estimated_daily_impact_inr") or "",
            ]
        )
    for rec in recommendations[:10]:
        rows.append(
            [
                rec.get("impact") or "medium",
                rec.get("title") or "Recommendation",
                "",
                "PHOTO-DETECTED",
                rec.get("detail") or "",
                "",
            ]
        )
    if len(rows) == 1:
        rows.append(["—", "No critical actions", "", "", "", ""])
    return rows


def _section8_rows(ctx: dict) -> list[list]:
    rows = [["Item", "Detail"]]
    for line in _CAPTURE_LIMITATIONS:
        rows.append(["Limitation", line])
    rows.append(["Enabled modules", "; ".join(ctx.get("enabled_modules") or [])])
    rows.append(["Omitted modules", "; ".join(ctx.get("omitted_modules") or [])])
    rows.append(["Evidence package", "Original photo, annotated image, product table, this report"])
    return rows


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
    report_context: dict | None = None,
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

    ctx = report_context or build_report_context(scan_id=scan_id or "", metrics=metrics)
    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    lines: list[str] = [
        f"# {REPORT_TITLE}",
        f"# Report ID,{_csv_escape(ctx.get('report_id') or scan_id or '')}",
        f"# Status,{_csv_escape(ctx.get('status', 'DRAFT'))}",
        f"# Analysis date,{now}",
        f"# Spec version,{REPORT_SPEC_VERSION}",
    ]
    lines.extend(_csv_section("Section 1 — Purpose scope and business context", _section1_rows(ctx)))
    if executive_summary:
        lines.extend(
            _csv_section(
                "Executive summary",
                [["Executive summary"], [_na(executive_summary)]],
            )
        )
    lines.extend(_csv_section("Section 2 — Inputs and analysis method", _section2_rows(ctx, metrics)))
    lines.extend(_csv_section("Section 3 — Shelf location and reference fields", _section3_rows(ctx, metrics)))
    lines.extend(_csv_section("Section 4 — Product and observation fields", _inventory_observation_rows(inventory)))
    lines.extend(_csv_section("Section 5 — Core calculations and KPIs", _kpi_export_rows(metrics)))
    if shares:
        lines.extend(
            _csv_section(
                "Section 5b — Brand facing share",
                [["Brand", "Share %"]]
                + [[row.get("brand", ""), f"{float(row.get('share', 0)):.1f}"] for row in shares[:15]],
            )
        )
    lines.extend(_csv_section("Section 6 — Optional inventory and commercial KPIs", _section6_rows(metrics)))
    lines.extend(
        _csv_section(
            "Section 7 — Findings and corrective actions",
            _action_rows(metrics, recommendations or []),
        )
    )
    if compliance_alerts:
        lines.extend(
            _csv_section(
                "Section 7b — Compliance alerts",
                [["Severity", "Title", "Detail"]]
                + [[a.get("severity", ""), a.get("title", ""), a.get("detail", "")] for a in compliance_alerts[:20]],
            )
        )
    if alerts:
        lines.extend(
            _csv_section(
                "Section 7c — Operational alerts",
                [["Severity", "Title", "Detail"]]
                + [[a.get("severity", ""), a.get("title", ""), a.get("detail", "")] for a in alerts[:20]],
            )
        )
    lines.extend(_csv_section("Section 8 — Validation limitations and evidence", _section8_rows(ctx)))
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


def _append_annotated_shelf_section(story: list, styles, annotated_jpeg: bytes, *, heading: str = "Annotated shelf image") -> None:
    """Insert annotated shelf image (same JPEG as scan result download)."""
    section = [
        Paragraph(f"<b>{heading}</b>", styles["Heading3"]),
        Paragraph(
            "<i>PHOTO-DETECTED evidence — green = OK, red = mismatch. Not an approved planogram.</i>",
            styles["Normal"],
        ),
        Spacer(1, 0.08 * inch),
        _annotated_image_flowable(annotated_jpeg),
    ]
    story.append(KeepTogether(section))
    story.append(Spacer(1, 0.2 * inch))


def _styled_table(rows: list[list], col_widths: list[float] | None = None) -> Table:
    table = Table(rows, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#09283e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _append_pdf_section(story: list, styles, title: str, rows: list[list], col_widths: list[float] | None = None) -> None:
    story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
    if rows:
        story.append(_styled_table(rows, col_widths))
    story.append(Spacer(1, 0.15 * inch))


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
    report_context: dict | None = None,
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
    ctx = report_context or build_report_context(scan_id=scan_id, metrics=metrics)
    now = datetime.now()

    if logo_path and logo_path.exists():
        story.append(_logo_flowable(logo_path))
        story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph(f"<b>{REPORT_TITLE}</b>", styles["Title"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"<b>Report ID:</b> {scan_id}", styles["Normal"]))
    story.append(Paragraph(f"<b>Status:</b> {ctx.get('status', 'DRAFT')}", styles["Normal"]))
    story.append(Paragraph(f"<b>Analysis date:</b> {now.strftime('%d-%m-%Y %H:%M')}", styles["Normal"]))
    story.append(Paragraph(f"<b>System version:</b> {ctx.get('model_version', 'aislix')}", styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))

    _append_pdf_section(
        story,
        styles,
        "Section 1 — Purpose, scope and business context",
        _section1_rows(ctx),
        [1.6 * inch, 3.4 * inch],
    )
    _append_executive_summary(story, styles, executive_summary)
    _append_pdf_section(
        story,
        styles,
        "Section 2 — Inputs and analysis method",
        _section2_rows(ctx, metrics),
        [1.8 * inch, 3.2 * inch],
    )
    _append_pdf_section(
        story,
        styles,
        "Section 3 — Shelf, location and reference fields",
        _section3_rows(ctx, metrics),
        [1.8 * inch, 3.2 * inch],
    )

    obs_rows = _inventory_observation_rows(inventory)
    _append_pdf_section(
        story,
        styles,
        "Section 4 — Product and observation fields",
        [[str(c)[:32] for c in row] for row in obs_rows[:35]],
        [0.6 * inch, 0.9 * inch, 0.55 * inch, 0.35 * inch, 0.4 * inch, 0.7 * inch, 0.75 * inch, 0.5 * inch, 0.55 * inch],
    )

    kpi_rows = _kpi_export_rows(metrics)
    _append_pdf_section(
        story,
        styles,
        "Section 5 — Core calculations and KPIs",
        [[str(c) for c in row] for row in kpi_rows],
        [1.3 * inch, 0.7 * inch, 0.55 * inch, 0.55 * inch, 0.55 * inch, 0.55 * inch, 0.8 * inch],
    )

    intel = metrics.get("retail_intelligence") or {}
    dashboard = intel.get("audit_kpi_dashboard") or {}
    if dashboard.get("primary_kpis"):
        role_label = dashboard.get("role_label") or dashboard.get("role_id") or "Audit"
        story.append(Paragraph(f"<b>Section 5a — {role_label} primary KPIs (five-card audit)</b>", styles["Heading2"]))
        if dashboard.get("introduction"):
            story.append(Paragraph(_ascii_label(str(dashboard["introduction"])), styles["Normal"]))
        audit_rows = _audit_kpi_pdf_rows(metrics)
        story.append(_styled_table(audit_rows, [1.45 * inch, 0.75 * inch, 0.65 * inch, 0.75 * inch, 0.55 * inch, 0.55 * inch]))
        story.append(Spacer(1, 0.15 * inch))

    plano_exc = _planogram_exception_pdf_rows(metrics)
    if plano_exc:
        _append_pdf_section(
            story,
            styles,
            "Section 5b — Planogram exceptions",
            plano_exc,
            [1.1 * inch, 1.1 * inch, 0.75 * inch, 0.55 * inch, 1.0 * inch],
        )

    price_exc = _price_exception_pdf_rows(metrics)
    if price_exc:
        _append_pdf_section(
            story,
            styles,
            "Section 5c — Price label exceptions",
            price_exc,
            [1.4 * inch, 0.75 * inch, 0.75 * inch, 0.6 * inch, 0.75 * inch],
        )

    if shares:
        brand_rows = [["Brand", "Share %"]] + [[row["brand"], f"{row['share']:.1f}"] for row in shares[:10]]
        _append_pdf_section(story, styles, "Section 5d — Brand facing share", brand_rows, [3 * inch, 1.2 * inch])

    _append_pdf_section(
        story,
        styles,
        "Section 6 — Optional inventory and commercial KPIs",
        _section6_rows(metrics),
        [1.8 * inch, 1.2 * inch, 1.5 * inch],
    )

    action_rows = _action_rows(metrics, recommendations)
    _append_pdf_section(
        story,
        styles,
        "Section 7 — Findings and corrective actions",
        [[str(c)[:40] for c in row] for row in action_rows[:18]],
        [0.55 * inch, 1.0 * inch, 0.85 * inch, 0.75 * inch, 1.35 * inch, 0.7 * inch],
    )

    if compliance_alerts:
        story.append(Paragraph(f"<b>{COMPLIANCE_ALERT_TITLE}</b>", styles["Heading3"]))
        story.append(Paragraph(f"<i>{COMPLIANCE_ALERT_INTERPRETATION}</i>", styles["Normal"]))
        for alert in compliance_alerts[:6]:
            severity = (alert.get("severity") or "medium").upper()
            detail = alert.get("detail") or ""
            line = f"<b>[{severity}]</b> {alert.get('title') or COMPLIANCE_ALERT_TITLE}"
            if detail:
                line += f" — {detail}"
            story.append(Paragraph(line, styles["Normal"]))
        if subcategory_mismatches:
            mismatch_rows = [["Brand", "Product", "Detected", "Expected", "Qty"]] + [
                [
                    row.get("brand", ""),
                    (row.get("product_name") or "")[:24],
                    row.get("detected_sub_category_label", ""),
                    row.get("expected_sub_category_label", ""),
                    str(row.get("quantity", 0)),
                ]
                for row in subcategory_mismatches[:10]
            ]
            story.append(_styled_table(mismatch_rows, [0.85 * inch, 1.35 * inch, 0.85 * inch, 0.85 * inch, 0.4 * inch]))
        story.append(Spacer(1, 0.15 * inch))

    other_alerts = [a for a in alerts if a.get("category") != "compliance"]
    for alert in (other_alerts or alerts)[:6]:
        severity = (alert.get("severity") or "medium").upper()
        title = alert.get("title") or "Alert"
        detail = alert.get("detail") or ""
        line = f"<b>[{severity}]</b> {title}"
        if detail:
            line += f" — {detail}"
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))

    _append_pdf_section(
        story,
        styles,
        "Section 8 — Validation, limitations and supporting evidence",
        _section8_rows(ctx),
        [1.4 * inch, 3.6 * inch],
    )

    if annotated_jpeg is None and annotated_image is not None and annotated_image.size > 0:
        annotated_jpeg = encode_annotated_image_bytes(annotated_image)
    if annotated_jpeg:
        _append_annotated_shelf_section(story, styles, annotated_jpeg, heading="Supporting evidence — annotated shelf image")

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
