"""Shelf metrics, brand share, alerts, and recommendations."""

from __future__ import annotations

from app.scan_context import COMPLIANCE_ALERT_INTERPRETATION, COMPLIANCE_ALERT_TITLE

LOW_STOCK_THRESHOLD = 2
OCR_LOW_CONFIDENCE_THRESHOLD = 0.55


def ocr_quality_metrics(classified: list[dict]) -> dict:
    """Aggregate OCR health across facings for scan summary."""
    if not classified:
        return {
            "ocr_empty_facings": 0,
            "ocr_low_confidence_facings": 0,
            "ocr_avg_confidence": 0.0,
        }
    empty = 0
    low = 0
    confidences: list[float] = []
    for row in classified:
        pack_text = (row.get("pack_text") or "").strip()
        ocr_conf = float(row.get("ocr_confidence") or 0.0)
        if len(pack_text) < 3:
            empty += 1
        elif ocr_conf < OCR_LOW_CONFIDENCE_THRESHOLD:
            low += 1
        if ocr_conf > 0:
            confidences.append(ocr_conf)
    return {
        "ocr_empty_facings": empty,
        "ocr_low_confidence_facings": low,
        "ocr_avg_confidence": round(sum(confidences) / max(len(confidences), 1), 4),
    }


def shelf_utilization(classified: list[dict], image_shape: tuple[int, int, int]) -> float:
    h, w = image_shape[:2]
    image_area = max(h * w, 1)
    box_area = 0
    for item in classified:
        x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]
        box_area += max(0, x2 - x1) * max(0, y2 - y1)
    return round(min(100.0, (box_area / image_area) * 100), 2)


def compute_metrics(
    inventory: list[dict],
    classified: list[dict],
    image_shape,
    processing_ms: int,
    *,
    misplaced_facings: int = 0,
) -> dict:
    total_facings = len(classified)
    unique_skus = len(inventory)
    brands = {row["brand"] for row in inventory if row.get("brand")}
    low_stock = sum(1 for row in inventory if row["quantity"] <= LOW_STOCK_THRESHOLD)
    confidences = [float(row.get("confidence") or 0.0) for row in inventory]
    avg_conf = sum(confidences) / max(len(confidences), 1)
    utilization = shelf_utilization(classified, image_shape)
    osa = round(((total_facings - 0) / max(total_facings, 1)) * 100, 2)
    health = round(osa * 0.6 + utilization * 0.25 + avg_conf * 100 * 0.15, 2)
    if misplaced_facings > 0 and total_facings > 0:
        penalty = min(10.0, (misplaced_facings / total_facings) * 100 * 0.1)
        health = round(max(0.0, health - penalty), 2)

    mismatch_skus = sum(1 for row in inventory if row.get("compliance_status") == "category_mismatch")

    return {
        "total_products": sum(row["quantity"] for row in inventory),
        "total_facings": total_facings,
        "unique_skus": unique_skus,
        "unique_brands": len(brands),
        "low_stock_products": low_stock,
        "out_of_stock_products": 0,
        "misplaced_products": misplaced_facings,
        "subcategory_mismatch_skus": mismatch_skus,
        "average_confidence": round(avg_conf, 4),
        "osa_percent": osa,
        "share_of_shelf_percent": utilization,
        "shelf_utilization_percent": utilization,
        "shelf_health_score": health,
        "processing_time_ms": processing_ms,
    }


def brand_share(inventory: list[dict]) -> list[dict]:
    totals: dict[str, int] = {}
    grand = 0
    for row in inventory:
        brand = row.get("brand") or "Unknown"
        totals[brand] = totals.get(brand, 0) + row["quantity"]
        grand += row["quantity"]
    if not grand:
        return []
    return [
        {"brand": brand, "share": round((qty / grand) * 100, 1)}
        for brand, qty in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def category_breakdown(inventory: list[dict]) -> list[dict]:
    totals: dict[str, int] = {}
    for row in inventory:
        cat = row.get("category") or "General"
        totals[cat] = totals.get(cat, 0) + row["quantity"]
    return [
        {"category": cat, "count": count}
        for cat, count in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def build_alerts(
    metrics: dict,
    compliance_alerts: list[dict] | None = None,
) -> list[dict]:
    alerts: list[dict] = []
    compliance_alerts = compliance_alerts or []

    for alert in compliance_alerts:
        alerts.append({**alert})

    if metrics["low_stock_products"] > 0:
        alerts.append(
            {
                "id": "low-stock",
                "severity": "high" if metrics["low_stock_products"] > 10 else "medium",
                "title": f"{metrics['low_stock_products']} products are low on stock",
                "detail": f"Threshold: {LOW_STOCK_THRESHOLD} facings or fewer.",
            }
        )
    if metrics["average_confidence"] < 0.6:
        alerts.append(
            {
                "id": "confidence",
                "severity": "medium",
                "title": "Average AI confidence is below 60%",
                "detail": "Consider retaking the shelf photo with better lighting.",
            }
        )
    return alerts


def build_recommendations(
    metrics: dict,
    inventory: list[dict],
    compliance_alerts: list[dict] | None = None,
) -> list[dict]:
    recs = []
    compliance_alerts = compliance_alerts or []

    if compliance_alerts:
        primary = compliance_alerts[0]
        recs.append(
            {
                "id": "putaway-violation",
                "title": COMPLIANCE_ALERT_TITLE,
                "detail": (
                    f"{COMPLIANCE_ALERT_INTERPRETATION}. "
                    f"{primary.get('detail') or 'Review shelf placement and correct misplaced facings.'}"
                ),
                "category": "Compliance",
                "impact": "high",
            }
        )

    if metrics["low_stock_products"] > 0:
        recs.append(
            {
                "id": "replenish",
                "title": f"Replenish {metrics['low_stock_products']} low-stock SKUs",
                "detail": "Prioritize restocking items at or below facing threshold.",
                "category": "Replenishment",
                "impact": "high",
            }
        )
    if inventory:
        top_brand = inventory[0]["brand"]
        recs.append(
            {
                "id": "brand-focus",
                "title": f"Top brand on shelf: {top_brand}",
                "detail": "Review share-of-shelf against planogram targets.",
                "category": "Merchandising",
                "impact": "medium",
            }
        )
    return recs


def executive_summary(metrics: dict, compliance_alerts: list[dict] | None = None) -> str:
    base = (
        f"This shelf audit detected {metrics['total_products']} product facings across "
        f"{metrics['unique_skus']} unique SKUs and {metrics['unique_brands']} brands. "
        f"Shelf utilization is {metrics['share_of_shelf_percent']:.1f}% with an average "
        f"AI confidence of {metrics['average_confidence'] * 100:.1f}%."
    )
    if metrics.get("misplaced_products", 0) > 0:
        base += (
            f" {COMPLIANCE_ALERT_TITLE}: {metrics['misplaced_products']} facing(s) — "
            f"{COMPLIANCE_ALERT_INTERPRETATION}."
        )
    return base
