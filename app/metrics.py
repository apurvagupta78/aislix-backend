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


def finalize_execution_score(metrics: dict) -> None:
    """Recompute shelf execution after planogram fields are merged into metrics."""
    planogram = metrics.get("planogram_compliance_percent")
    planogram_val = float(planogram) if planogram is not None else None
    metrics["shelf_execution_score"] = compute_shelf_execution_score(
        availability_percent=float(metrics.get("availability_percent") or metrics.get("osa_percent") or 0),
        planogram_percent=planogram_val,
        facing_compliance_percent=float(metrics.get("facing_compliance_percent") or 0),
        placement_compliance_percent=float(metrics.get("placement_compliance_percent") or 0),
    )


def compute_shelf_execution_score(
    *,
    availability_percent: float,
    planogram_percent: float | None,
    facing_compliance_percent: float,
    placement_compliance_percent: float,
) -> float:
    """Retail execution score — excludes model confidence."""
    if planogram_percent is not None:
        return round(
            availability_percent * 0.30
            + planogram_percent * 0.25
            + facing_compliance_percent * 0.25
            + placement_compliance_percent * 0.20,
            1,
        )
    return round(
        availability_percent * 0.35
        + facing_compliance_percent * 0.35
        + placement_compliance_percent * 0.30,
        1,
    )


def compute_metrics(
    inventory: list[dict],
    classified: list[dict],
    image_shape,
    processing_ms: int,
    *,
    misplaced_facings: int = 0,
    planogram_compliance_percent: float | None = None,
) -> dict:
    total_facings = len(classified)
    counted_inventory = [row for row in inventory if row.get("counted_in_totals", True)]
    unique_skus = len(counted_inventory)
    brands = {row["brand"] for row in counted_inventory if row.get("brand")}
    low_stock = sum(1 for row in counted_inventory if row["quantity"] <= LOW_STOCK_THRESHOLD)
    confirmed_oos = sum(1 for row in counted_inventory if int(row.get("quantity") or 0) == 0)
    confidences = [float(row.get("confidence") or 0.0) for row in counted_inventory]
    avg_conf = sum(confidences) / max(len(confidences), 1)
    utilization = shelf_utilization(classified, image_shape)

    needs_review = sum(
        1
        for row in classified
        if row.get("exclude_from_inventory")
        or (row.get("brand") or "").strip().lower() in {"", "unknown"}
        or (row.get("product_name") or "").strip().lower() in {"", "unknown", "unidentified sku"}
    )
    identified_facings = max(0, total_facings - needs_review)
    recognition_coverage = round((identified_facings / max(total_facings, 1)) * 100, 1)

    # Availability: penalise low-stock SKUs relative to assortment size (not raw facing count).
    low_stock_penalty = (low_stock / max(unique_skus, 1)) * 100
    availability = round(max(0.0, min(100.0, 100.0 - low_stock_penalty * 0.6 - confirmed_oos * 5)), 1)

    placement_compliance = round(
        max(0.0, 100.0 - (misplaced_facings / max(total_facings, 1)) * 100),
        1,
    )
    facing_compliance = placement_compliance
    if planogram_compliance_percent is not None:
        facing_compliance = round(
            (placement_compliance + float(planogram_compliance_percent)) / 2,
            1,
        )

    execution = compute_shelf_execution_score(
        availability_percent=availability,
        planogram_percent=planogram_compliance_percent,
        facing_compliance_percent=facing_compliance,
        placement_compliance_percent=placement_compliance,
    )

    # Legacy health score (kept for backward compatibility on old dashboards).
    health = round(osa := availability, 2)
    if misplaced_facings > 0 and total_facings > 0:
        penalty = min(10.0, (misplaced_facings / total_facings) * 100 * 0.1)
        health = round(max(0.0, health - penalty), 2)

    mismatch_skus = sum(1 for row in inventory if row.get("compliance_status") == "category_mismatch")
    possible_oos = low_stock
    shelf_gap_count = max(0, needs_review)

    return {
        "total_products": sum(row["quantity"] for row in counted_inventory),
        "total_facings": total_facings,
        "unique_skus": unique_skus,
        "unique_brands": len(brands),
        "low_stock_products": low_stock,
        "out_of_stock_products": confirmed_oos,
        "confirmed_oos_count": confirmed_oos,
        "possible_oos_count": possible_oos,
        "shelf_gap_count": shelf_gap_count,
        "misplaced_products": misplaced_facings,
        "placement_issue_count": misplaced_facings,
        "subcategory_mismatch_skus": mismatch_skus,
        "needs_review_facings": needs_review,
        "excluded_from_count_facings": sum(
            1 for row in classified if row.get("exclude_from_inventory")
        ),
        "average_confidence": round(avg_conf, 4),
        "recognition_coverage_percent": recognition_coverage,
        "osa_percent": osa,
        "availability_percent": availability,
        "facing_compliance_percent": facing_compliance,
        "placement_compliance_percent": placement_compliance,
        "share_of_shelf_percent": utilization,
        "shelf_utilization_percent": utilization,
        "shelf_health_score": health,
        "shelf_execution_score": execution,
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "processing_time_ms": processing_ms,
    }


def compute_competitor_intel(
    brand_share_rows: list[dict],
    *,
    primary_brand: str | None,
    competitor_brands: list[str] | None,
) -> dict | None:
    """Own-brand vs configured competitor facings share."""
    primary = (primary_brand or "").strip()
    if not primary or not brand_share_rows:
        return None

    competitors = [b.strip() for b in (competitor_brands or []) if b and str(b).strip()]
    by_key: dict[str, dict] = {}
    for row in brand_share_rows:
        brand = (row.get("brand") or "").strip()
        if not brand:
            continue
        by_key[brand.lower()] = row

    own_row = by_key.get(primary.lower(), {})
    own_share = float(own_row.get("share") or 0.0)
    competitor_shares: list[dict] = []
    detected = 0
    for name in competitors:
        row = by_key.get(name.lower(), {})
        share = float(row.get("share") or 0.0)
        if share > 0:
            detected += 1
        competitor_shares.append(
            {
                "brand": name,
                "share": round(share, 1),
                "quantity": int(row.get("quantity") or 0),
                "is_competitor": True,
            }
        )

    return {
        "primary_brand": primary,
        "own_brand_share_percent": round(own_share, 1),
        "competitor_shares": [
            {
                "brand": primary,
                "share": round(own_share, 1),
                "quantity": int(own_row.get("quantity") or 0),
                "is_primary": True,
            },
            *competitor_shares,
        ],
        "competitors_detected": detected,
        "competitors_configured": len(competitors),
    }


def brand_share(
    inventory: list[dict],
    *,
    exclude_category_mismatch: bool = False,
) -> list[dict]:
    """Share of shelf facings by brand (quantity-weighted)."""
    totals: dict[str, int] = {}
    grand = 0
    for row in inventory:
        if exclude_category_mismatch and (row.get("compliance_status") or "").lower() == "category_mismatch":
            continue
        brand = (row.get("brand") or "Unknown").strip() or "Unknown"
        qty = int(row.get("quantity") or row.get("facings") or 0)
        if qty <= 0:
            continue
        totals[brand] = totals.get(brand, 0) + qty
        grand += qty
    if not grand:
        return []
    return [
        {
            "brand": brand,
            "quantity": qty,
            "share": round((qty / grand) * 100, 1),
        }
        for brand, qty in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def build_brand_share_payload(
    inventory: list[dict],
    *,
    audit_sub_category: str | None = None,
) -> dict:
    """Canonical brand-share fields for dashboard + landing (same math, same scope)."""
    from app.inventory import inventory_counted_rows

    counted = inventory_counted_rows(inventory)
    all_rows = brand_share(counted, exclude_category_mismatch=False)
    audit_rows = brand_share(counted, exclude_category_mismatch=True)
    use_audit = bool((audit_sub_category or "").strip())
    primary = audit_rows if use_audit else all_rows
    denominator = sum(row["quantity"] for row in primary)
    return {
        "brand_share": primary,
        "top_brands": primary[:10],
        "brand_share_all": all_rows,
        "brand_share_scope": "in_audit" if use_audit else "all",
        "brand_share_denominator": denominator,
    }


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

    if metrics.get("confirmed_oos_count", 0) > 0:
        alerts.append(
            {
                "id": "oos",
                "severity": "high",
                "title": f"{metrics['confirmed_oos_count']} confirmed out-of-stock SKUs",
                "detail": "Expected assortment items were not detected on the shelf.",
            }
        )
    if metrics["low_stock_products"] > 0:
        alerts.append(
            {
                "id": "low-stock",
                "severity": "high" if metrics["low_stock_products"] > 10 else "medium",
                "title": f"{metrics['low_stock_products']} SKUs below facing threshold",
                "detail": f"Threshold: {metrics.get('low_stock_threshold', LOW_STOCK_THRESHOLD)} facings or fewer.",
            }
        )
    if metrics.get("placement_issue_count", 0) > 0:
        alerts.append(
            {
                "id": "placement",
                "severity": "high",
                "title": f"{metrics['placement_issue_count']} placement issues detected",
                "detail": COMPLIANCE_ALERT_INTERPRETATION,
            }
        )
    return alerts


def build_recommendations(
    metrics: dict,
    inventory: list[dict],
    compliance_alerts: list[dict] | None = None,
) -> list[dict]:
    recs: list[dict] = []
    compliance_alerts = compliance_alerts or []
    threshold = int(metrics.get("low_stock_threshold") or LOW_STOCK_THRESHOLD)

    if metrics.get("confirmed_oos_count", 0) > 0:
        recs.append(
            {
                "id": "replenish-oos",
                "title": f"Replenish {metrics['confirmed_oos_count']} out-of-stock SKUs",
                "detail": "Priority items from your assortment are missing from the shelf.",
                "category": "Replenishment",
                "impact": "high",
                "priority": "high",
                "action_type": "oos",
            }
        )

    if metrics["low_stock_products"] > 0:
        recs.append(
            {
                "id": "replenish-low",
                "title": f"Replenish {metrics['low_stock_products']} low-stock SKUs",
                "detail": f"SKUs at or below {threshold} facings need restocking.",
                "category": "Replenishment",
                "impact": "high",
                "priority": "high",
                "action_type": "low_stock",
            }
        )

    placement_count = int(metrics.get("placement_issue_count") or metrics.get("misplaced_products") or 0)
    if placement_count > 0:
        primary = compliance_alerts[0] if compliance_alerts else None
        recs.append(
            {
                "id": "fix-placement",
                "title": f"Fix {placement_count} misplaced facings",
                "detail": primary.get("detail") if primary else COMPLIANCE_ALERT_INTERPRETATION,
                "category": "Placement",
                "impact": "high",
                "priority": "high",
                "action_type": "placement",
            }
        )

    if metrics.get("planogram_compliance_percent") is not None and metrics["planogram_compliance_percent"] < 85:
        recs.append(
            {
                "id": "planogram",
                "title": "Restore planogram compliance",
                "detail": f"Compliance is {metrics['planogram_compliance_percent']:.0f}% — review expected vs actual layout.",
                "category": "Planogram",
                "impact": "medium",
                "priority": "medium",
                "action_type": "planogram",
            }
        )

    return recs


# Indicative FMCG defaults when SKU price is unknown (INR).
_DEFAULT_ASP_INR = 75.0
_UNITS_PER_DAY = 4.0
_LOW_STOCK_RISK_FACTOR = 0.35


def _planogram_pricing_lookup(planogram_items: list[dict] | None) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in planogram_items or []:
        key = str(item.get("match_key") or "").strip().lower()
        if not key:
            brand = str(item.get("brand") or "").strip().lower()
            product = str(item.get("product_name") or "").strip().lower()
            variant = str(item.get("variant") or "").strip().lower()
            key = "|".join(p for p in (brand, product, variant) if p)
        if key:
            lookup[key] = item
    return lookup


def _row_planogram_key(row: dict) -> str:
    key = str(row.get("match_key") or "").strip().lower()
    if key:
        return key
    brand = str(row.get("brand") or "").strip().lower()
    product = str(row.get("product") or row.get("product_name") or "").strip().lower()
    variant = str(row.get("variant") or "").strip().lower()
    return "|".join(p for p in (brand, product, variant) if p)


def _pricing_for_planogram_row(row: dict) -> tuple[float, float, bool]:
    asp = float(row.get("mrp_inr") or row.get("price_inr") or _DEFAULT_ASP_INR)
    velocity = float(row.get("avg_daily_sales") or _UNITS_PER_DAY)
    priced = bool(row.get("mrp_inr") or row.get("avg_daily_sales"))
    return asp, velocity, priced


def compute_financial_impact(
    inventory: list[dict],
    metrics: dict,
    planogram_items: list[dict] | None = None,
    planogram_compliance: dict | None = None,
) -> dict:
    """Estimate daily / weekly lost sales from OOS and low-stock SKUs."""
    counted = [row for row in inventory if row.get("counted_in_totals", True)]
    plano_lookup = _planogram_pricing_lookup(planogram_items)
    oos_daily = 0.0
    at_risk_daily = 0.0
    oos_skus = 0
    at_risk_skus = 0
    threshold = int(metrics.get("low_stock_threshold") or LOW_STOCK_THRESHOLD)
    used_planogram_pricing = False

    compliance_lines = (planogram_compliance or {}).get("lines") or []
    if planogram_items and compliance_lines:
        plano_by_key = {
            _row_planogram_key(item): item for item in planogram_items if _row_planogram_key(item)
        }
        for line in compliance_lines:
            issue = str(line.get("issue_type") or "")
            if issue in {"correct", "ok"}:
                continue
            exp_brand = str(line.get("expected_brand") or "").strip().lower()
            exp_product = str(line.get("expected_product") or "").strip().lower()
            key = "|".join(p for p in (exp_brand, exp_product) if p)
            plano = plano_by_key.get(key) or {}
            asp, velocity, priced = _pricing_for_planogram_row(plano)
            if priced:
                used_planogram_pricing = True
            exp_qty = int(line.get("expected_qty") or 1)
            act_qty = int(line.get("actual_qty") or 0)
            if issue in {"missing", "wrong_product", "wrong_category", "wrong_location"}:
                oos_daily += velocity * asp * max(exp_qty, 1)
                oos_skus += 1
            elif issue in {"qty_mismatch", "qty_issue"} and act_qty < exp_qty:
                gap = exp_qty - act_qty
                at_risk_daily += gap * velocity * asp * _LOW_STOCK_RISK_FACTOR
                at_risk_skus += 1
    elif planogram_items:
        for plan in planogram_items:
            asp, velocity, priced = _pricing_for_planogram_row(plan)
            if priced:
                used_planogram_pricing = True
            exp_qty = max(1, int(plan.get("expected_qty") or 1))
            key = _row_planogram_key(plan)
            detected = 0
            for row in counted:
                if _row_planogram_key(row) == key:
                    detected = int(row.get("quantity") or 0)
                    break
            if detected <= 0:
                oos_daily += velocity * asp * exp_qty
                oos_skus += 1
            elif detected < exp_qty:
                gap = exp_qty - detected
                at_risk_daily += gap * velocity * asp * _LOW_STOCK_RISK_FACTOR
                at_risk_skus += 1
            elif detected < threshold:
                gap = max(0, threshold - detected)
                at_risk_daily += gap * velocity * asp
                at_risk_skus += 1
    else:
        for row in counted:
            qty = int(row.get("quantity") or 0)
            asp = float(row.get("price_inr") or row.get("avg_price_inr") or _DEFAULT_ASP_INR)
            velocity = _UNITS_PER_DAY
            plano = plano_lookup.get(_row_planogram_key(row))
            if plano:
                if plano.get("mrp_inr") not in (None, ""):
                    asp = float(plano["mrp_inr"])
                    used_planogram_pricing = True
                if plano.get("avg_daily_sales") not in (None, ""):
                    velocity = float(plano["avg_daily_sales"])
                    used_planogram_pricing = True
            if qty <= 0:
                oos_daily += velocity * asp
                oos_skus += 1
            elif qty <= threshold:
                gap = max(0, threshold - qty)
                at_risk_daily += gap * velocity * asp * _LOW_STOCK_RISK_FACTOR
                at_risk_skus += 1

    daily = round(oos_daily + at_risk_daily)
    if daily <= 0 and oos_skus == 0 and at_risk_skus == 0:
        return {
            "estimated_daily_lost_sales_inr": 0,
            "estimated_weekly_lost_sales_inr": 0,
            "estimated_monthly_lost_sales_inr": 0,
            "oos_sku_count": 0,
            "at_risk_sku_count": 0,
            "methodology": (
                "Indicative estimate using category ASP defaults and typical daily velocity."
            ),
            "confidence": "indicative",
        }

    methodology = (
        "Uses planogram MRP and daily sales velocity per SKU where provided."
        if used_planogram_pricing
        else (
            "Indicative estimate using category ASP defaults (₹75 when price unknown) "
            f"and {_UNITS_PER_DAY:.0f} units/day velocity per at-risk SKU."
        )
    )
    return {
        "estimated_daily_lost_sales_inr": daily,
        "estimated_weekly_lost_sales_inr": daily * 7,
        "estimated_monthly_lost_sales_inr": daily * 30,
        "oos_sku_count": oos_skus,
        "at_risk_sku_count": at_risk_skus,
        "methodology": methodology,
        "confidence": "planogram" if used_planogram_pricing else "indicative",
    }


def executive_summary(metrics: dict, compliance_alerts: list[dict] | None = None) -> str:
    facings = metrics.get("total_facings") or metrics.get("total_products") or 0
    execution = metrics.get("shelf_execution_score") or metrics.get("shelf_health_score") or 0
    recognition = metrics.get("recognition_coverage_percent") or 0
    base = (
        f"Aislix detected {facings} facings across {metrics['unique_skus']} unique SKUs and "
        f"{metrics['unique_brands']} brands. Recognition coverage is {recognition:.0f}%. "
        f"Shelf execution score is {execution:.0f}/100."
    )
    if metrics.get("misplaced_products", 0) > 0:
        base += (
            f" {metrics['misplaced_products']} placement issue(s) were detected — "
            f"{COMPLIANCE_ALERT_INTERPRETATION.lower()}."
        )
    if metrics.get("low_stock_products", 0) > 0:
        base += f" {metrics['low_stock_products']} SKU(s) are below the facing threshold."
    return base
