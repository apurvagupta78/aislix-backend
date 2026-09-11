"""
Aislix Retail Execution Intelligence — structured metrics for all customer modes.
Computes from CV detections + planogram + org config; merges GPT narrative without inventing facts.
"""

from __future__ import annotations

from app.metric_states import insufficient, merge_gpt_metric, metric_value, not_configured

LOW_STOCK_THRESHOLD = 2


def _commercial_impact_score(
    *,
    financial_inr: float,
    priority: str,
    confidence: float,
    urgency: str,
) -> float:
    pri = {"critical": 1.0, "high": 0.85, "medium": 0.6, "low": 0.35}.get(priority, 0.5)
    urg = {"critical": 1.0, "high": 0.9, "medium": 0.7, "low": 0.5}.get(urgency, 0.6)
    fin = min(financial_inr / 10000.0, 1.0) if financial_inr > 0 else 0.25
    return round(fin * pri * max(0.1, confidence) * urg * 100, 1)


def build_image_quality(metrics: dict, gpt: dict | None) -> dict:
    ocr_empty = int(metrics.get("ocr_empty_facings") or 0)
    ocr_low = int(metrics.get("ocr_low_confidence_facings") or 0)
    ocr_avg = float(metrics.get("ocr_avg_confidence") or 0)
    total = int(metrics.get("total_facings") or 0)
    coverage = float(metrics.get("recognition_coverage_percent") or 0)
    gpt_iq = (gpt or {}).get("image_quality") if isinstance(gpt, dict) else None
    ocr_assessed = bool(metrics.get("ocr_assessed")) or ocr_avg > 0 or (ocr_empty + ocr_low) > 0

    if total <= 0:
        base = {"overall_state": "insufficient_evidence", "rescan_recommended": True, "notes": "No facings detected."}
    else:
        blur_risk = ocr_assessed and ocr_low / max(total, 1) > 0.35
        empty_risk = ocr_assessed and ocr_empty / max(total, 1) > 0.25
        rescan = blur_risk or empty_risk or coverage < 50
        detection_score = max(0, min(100, round(100 - max(0, 50 - coverage))))
        if ocr_assessed:
            score = max(0, min(100, round(detection_score - ocr_empty * 2 - ocr_low * 1.5)))
        else:
            score = min(detection_score, 85)
        status = "retake_required" if rescan else ("acceptable" if score < 85 else "good")
        notes = []
        if blur_risk:
            notes.append("Low OCR confidence on multiple facings — consider retaking with better focus.")
        if empty_risk:
            notes.append("Many facings lack readable pack text.")
        if coverage < 50:
            notes.append("Recognition coverage is low — move closer or improve lighting.")
        if not ocr_assessed:
            notes.append(
                "OCR/price-tag quality not assessed — score reflects detection coverage only, not measured accuracy."
            )
        iq_state = "partial" if not ocr_assessed else "available"
        base = {
            "audit_image_quality_score": metric_value(score, iq_state),
            "detection_quality_score": metric_value(detection_score, "available"),
            "ocr_quality_assessed": ocr_assessed,
            "status": status,
            "overall_state": iq_state,
            "rescan_recommended": rescan,
            "notes": " ".join(notes) if notes else "Detection coverage acceptable for facing counts.",
        }

    if isinstance(gpt_iq, dict):
        base["gpt_notes"] = gpt_iq.get("notes")
        if gpt_iq.get("rescan_recommended") and not base.get("rescan_recommended"):
            base["rescan_recommended"] = bool(gpt_iq["rescan_recommended"])
    return base


def build_assortment(
    inventory: list[dict],
    planogram_items: list[dict] | None,
    planogram_compliance: dict | None,
) -> dict:
    if not planogram_items:
        return {
            "breadth_percent": not_configured("Target assortment not configured"),
            "missing_assortment": not_configured(),
            "target_sku_availability": not_configured("Target assortment not configured"),
            "state": "not_configured",
        }

    expected = len(planogram_items)
    lines = (planogram_compliance or {}).get("lines") or []
    detected_expected = sum(
        1 for line in lines if str(line.get("issue_type") or "") in {"correct", "ok", "qty_mismatch", "qty_issue"}
    )
    missing = max(0, expected - detected_expected)
    breadth = round(detected_expected / max(expected, 1) * 100, 1)
    return {
        "breadth_percent": metric_value(breadth, "available"),
        "missing_assortment": metric_value(missing, "available"),
        "expected_sku_count": metric_value(expected, "available"),
        "detected_expected_sku_count": metric_value(detected_expected, "available"),
        "target_sku_availability": metric_value(breadth, "available"),
        "state": "available",
    }


def build_availability(metrics: dict, inventory: list[dict], planogram_items: list[dict] | None) -> dict:
    verified_absence = int(metrics.get("verified_shelf_absence_count") or 0)
    confirmed_inventory = int(metrics.get("confirmed_inventory_stockout_count") or 0)
    confirmed_oos = int(
        metrics.get("confirmed_oos_count") or verified_absence + confirmed_inventory or 0
    )
    suspected_gaps = int(metrics.get("suspected_shelf_gap_count") or 0)
    low_stock = int(metrics.get("low_stock_products") or 0)
    possible_oos = int(metrics.get("possible_oos_count") or low_stock or 0)
    shelf_gaps = int(metrics.get("shelf_gap_count") or metrics.get("needs_review_facings") or 0)
    expected = len(planogram_items) if planogram_items else len(inventory)

    if planogram_items:
        oos_rate = round(confirmed_oos / max(expected, 1) * 100, 1)
        low_stock_rate = round(possible_oos / max(expected, 1) * 100, 1)
        osa = round(max(0.0, 100.0 - oos_rate - low_stock_rate * 0.5), 1)
        osa_state = "available"
    elif inventory:
        osa = float(metrics.get("availability_percent") or metrics.get("osa_percent") or 0)
        oos_rate = round(confirmed_oos / max(len(inventory), 1) * 100, 1)
        low_stock_rate = round(possible_oos / max(len(inventory), 1) * 100, 1)
        osa_state = "estimated"
    else:
        return {
            "confirmed_oos": metric_value(0, "insufficient_evidence"),
            "possible_oos": metric_value(0, "insufficient_evidence"),
            "low_stock": metric_value(0, "insufficient_evidence"),
            "shelf_gaps": metric_value(0, "insufficient_evidence"),
            "basic_osa": not_configured("Target assortment not configured"),
            "state": "not_configured",
        }

    return {
        "confirmed_oos": metric_value(confirmed_oos, "available" if confirmed_oos else "available"),
        "verified_shelf_absence": metric_value(verified_absence, "available"),
        "confirmed_inventory_stockout": metric_value(confirmed_inventory, "available"),
        "suspected_shelf_gaps": metric_value(suspected_gaps, "available"),
        "possible_oos": metric_value(possible_oos, "available"),
        "low_stock": metric_value(low_stock, "available"),
        "shelf_gaps": metric_value(shelf_gaps, "available"),
        "oos_rate_percent": metric_value(oos_rate, "available" if planogram_items else "estimated"),
        "low_stock_rate_percent": metric_value(low_stock_rate, "available" if planogram_items else "estimated"),
        "basic_osa": metric_value(osa, osa_state),
        "state": "available",
    }


def _planogram_has_expected_facings(planogram_items: list[dict] | None) -> bool:
    return any(item.get("expected_facings") not in (None, "") for item in (planogram_items or []))


def build_facings(
    planogram_compliance: dict | None,
    metrics: dict,
    planogram_items: list[dict] | None = None,
) -> dict:
    if not planogram_compliance:
        return {
            "facing_compliance": not_configured("Planogram not configured"),
            "facing_gap": not_configured(),
            "state": "not_configured",
        }
    if not _planogram_has_expected_facings(planogram_items):
        return {
            "facing_compliance": not_configured("Expected facings not configured on planogram"),
            "facing_gap": not_configured(),
            "state": "not_configured",
        }
    lines = planogram_compliance.get("lines") or []
    exp_sum = 0
    act_sum = 0
    gap_sum = 0
    for line in lines:
        exp = int(line.get("expected_facings") or line.get("expected_qty") or 0)
        act = int(line.get("actual_qty") or line.get("detected_qty") or 0)
        exp_sum += exp
        act_sum += min(act, exp)
        gap_sum += max(0, exp - act)
    compliance = round(act_sum / max(exp_sum, 1) * 100, 1) if exp_sum else None
    if compliance is None:
        raw = metrics.get("facing_compliance_percent")
        compliance = float(raw) if raw is not None else None
    if compliance is None:
        return {
            "facing_compliance": insufficient("Facing compliance could not be calculated"),
            "facing_gap": not_configured(),
            "state": "insufficient_evidence",
        }
    return {
        "expected_facings": metric_value(exp_sum, "available"),
        "actual_facings": metric_value(act_sum, "available"),
        "facing_gap": metric_value(gap_sum, "available"),
        "facing_compliance": metric_value(compliance, "available"),
        "state": "available",
    }


def build_opportunity_ledger(
    metrics: dict,
    inventory: list[dict],
    planogram_compliance: dict | None,
    next_best_actions: list[dict] | None,
) -> list[dict]:
    fi = metrics.get("financial_impact") or {}
    daily = float(fi.get("estimated_daily_lost_sales_inr") or 0)
    level = int(fi.get("level") or (2 if daily > 0 else 1))
    ledger: list[dict] = []

    for idx, action in enumerate(next_best_actions or []):
        if not isinstance(action, dict):
            continue
        priority = str(action.get("priority") or action.get("severity") or "medium").lower()
        conf = float(action.get("confidence") or 0.75)
        impact_inr = float(action.get("estimated_daily_impact_inr") or 0)
        if impact_inr <= 0 and level >= 2:
            impact_inr = daily / max(len(next_best_actions or [1]), 1)
        ledger.append(
            {
                "id": str(action.get("action_id") or f"opp-{idx}"),
                "issue": str(action.get("issue_type") or action.get("title") or "execution"),
                "sku": action.get("sku") or action.get("product"),
                "brand": action.get("brand"),
                "severity": str(action.get("severity") or priority),
                "priority": priority,
                "expected": action.get("expected_state"),
                "actual": action.get("actual_state"),
                "gap": action.get("gap"),
                "revenue_at_risk_inr": impact_inr if level >= 2 else None,
                "commercial_risk": fi.get("commercial_risk") if level < 2 else None,
                "source": fi.get("source") or "scan_analysis",
                "confidence": fi.get("confidence") or "indicative",
                "recommended_action": str(action.get("recommended_action") or action.get("title") or ""),
                "status": str(action.get("status") or "open"),
                "commercial_impact_score": _commercial_impact_score(
                    financial_inr=impact_inr,
                    priority=priority,
                    confidence=conf,
                    urgency=str(action.get("severity") or priority),
                ),
            }
        )

    if not ledger and planogram_compliance:
        for idx, line in enumerate((planogram_compliance.get("lines") or [])[:5]):
            issue = str(line.get("issue_type") or "")
            if issue in {"correct", "ok"}:
                continue
            exp_qty = int(line.get("expected_facings") or line.get("expected_qty") or 0)
            act_qty = int(line.get("actual_qty") or line.get("detected_qty") or 0)
            ledger.append(
                {
                    "id": f"plano-{idx}",
                    "issue": issue,
                    "sku": line.get("expected_product") or line.get("product"),
                    "brand": line.get("expected_brand") or line.get("brand"),
                    "severity": "high" if issue == "missing" else "medium",
                    "priority": "high" if issue == "missing" else "medium",
                    "expected": str(exp_qty) if exp_qty else None,
                    "actual": str(act_qty),
                    "gap": str(act_qty - exp_qty) if exp_qty else None,
                    "revenue_at_risk_inr": daily / max(len(planogram_compliance.get("lines") or [1]), 1) if level >= 2 else None,
                    "commercial_risk": fi.get("commercial_risk") if level < 2 else None,
                    "source": fi.get("source") or "planogram_match",
                    "confidence": fi.get("confidence") or "indicative",
                    "recommended_action": str(line.get("detail") or "Replenish or correct placement, then rescan."),
                    "status": "open",
                    "commercial_impact_score": _commercial_impact_score(
                        financial_inr=daily,
                        priority="high",
                        confidence=0.8,
                        urgency="high",
                    ),
                }
            )

    ledger = _dedupe_opportunity_ledger(ledger)
    ledger.sort(key=lambda row: float(row.get("commercial_impact_score") or 0), reverse=True)
    return ledger[:25]


def _dedupe_opportunity_ledger(ledger: list[dict]) -> list[dict]:
    """One root cause per brand/SKU — prefer higher impact and stronger evidence."""
    by_key: dict[str, dict] = {}
    issue_root = {
        "missing": "availability",
        "wrong_product": "availability",
        "oos": "availability",
        "low_stock": "availability",
        "qty_mismatch": "facing",
        "qty_issue": "facing",
        "placement": "placement",
    }
    for row in ledger:
        issue = str(row.get("issue") or "").lower()
        root = issue_root.get(issue, issue or "execution")
        brand = str(row.get("brand") or "").strip().lower()
        sku = str(row.get("sku") or "").strip().lower()
        key = f"{brand}|{sku}|{root}"
        existing = by_key.get(key)
        if existing is None or float(row.get("commercial_impact_score") or 0) > float(
            existing.get("commercial_impact_score") or 0
        ):
            by_key[key] = row
    return list(by_key.values())


def build_pricing(
    classified: list[dict],
    planogram_items: list[dict] | None,
) -> dict:
    from app.price_compliance import compute_price_compliance

    payload = compute_price_compliance(classified, planogram_items)
    state = payload.get("state") or "not_configured"
    if state == "not_configured":
        return {
            "compliance_percent": not_configured("Price rules not configured"),
            "state": "not_configured",
        }
    if state == "not_observable":
        return {
            "compliance_percent": insufficient(payload.get("methodology") or "Price tags not readable"),
            "state": "not_observable",
            "lines": payload.get("lines") or [],
            "methodology": payload.get("methodology"),
        }
    return {
        "compliance_percent": metric_value(payload.get("compliance_percent"), "available"),
        "checked_tags": metric_value(payload.get("checked_tags"), "available"),
        "compliant_tags": metric_value(payload.get("compliant_tags"), "available"),
        "lines": payload.get("lines") or [],
        "state": "available",
        "methodology": payload.get("methodology"),
    }


def build_presentability(metrics: dict, inventory: list[dict]) -> dict:
    """Presentability requires dedicated visual QA — do not infer from gaps/placement."""
    return {
        "score": not_configured("Presentability not assessed"),
        "state": "not_configured",
        "methodology": (
            "Presentability requires visual analysis of alignment, orientation, and packaging condition."
        ),
    }


def build_shelf_structure(metrics: dict) -> dict:
    rows = metrics.get("yolo_row_counts")
    if not rows:
        return {"state": "insufficient_evidence", "shelf_count": insufficient()}
    return {
        "state": "available",
        "shelf_count": metric_value(len(rows) if isinstance(rows, list) else int(rows or 0), "available"),
        "shelf_levels": metric_value(rows, "available") if isinstance(rows, list) else insufficient(),
    }


def _mode_insights(customer_type: str | None, metrics: dict) -> dict:
    ct = (customer_type or "").lower()
    if ct == "darkstore":
        return {
            "mode": "dark_store",
            "pick_face_availability": metrics.get("availability_percent"),
            "note": "Operational pick metrics require slot configuration.",
        }
    if ct == "fmcg":
        return {"mode": "fmcg", "priority": "share_of_facings, planogram, OSA, competitor share"}
    if ct == "local":
        return {"mode": "local_retailer", "priority": "OOS, low stock, top 5 actions"}
    if ct == "distributor":
        return {"mode": "distributor", "priority": "assortment, expiry, damaged stock"}
    return {"mode": "supermarket", "priority": "availability, planogram, presentability"}


def build_retail_intelligence(
    *,
    metrics: dict,
    inventory: list[dict],
    classified: list[dict],
    planogram_compliance: dict | None,
    planogram_items: list[dict] | None,
    scan_context: dict | None,
    gpt_intel: dict | None,
    next_best_actions: list[dict] | None,
    customer_type: str | None = None,
) -> dict:
    """Assemble full retail_intelligence block for metrics JSONB."""
    gpt = gpt_intel if isinstance(gpt_intel, dict) else {}
    ctx = scan_context or {}

    recognition = merge_gpt_metric(
        metric_value(metrics.get("recognition_coverage_percent"), "available"),
        gpt.get("recognition_coverage"),
    )
    ai_conf = merge_gpt_metric(
        metric_value(
            round(float(metrics.get("average_confidence") or 0) * 100, 1)
            if float(metrics.get("average_confidence") or 0) <= 1
            else round(float(metrics.get("average_confidence") or 0), 1),
            "available",
        ),
        gpt.get("ai_confidence"),
    )

    share_of_facings = metric_value(metrics.get("share_of_shelf_percent"), "available")
    if planogram_items or ctx.get("primary_brand"):
        share_of_facings = metric_value(
            (metrics.get("top_brands") or [{}])[0].get("share") if metrics.get("top_brands") else None,
            "available" if metrics.get("top_brands") else "not_configured",
            label="Share of facings",
        )

    intel = {
        "recognition_coverage": recognition,
        "ai_confidence": ai_conf,
        "image_quality": build_image_quality(metrics, gpt),
        "shelf_structure": build_shelf_structure(metrics),
        "assortment": build_assortment(inventory, planogram_items, planogram_compliance),
        "availability": build_availability(metrics, inventory, planogram_items),
        "facings": build_facings(planogram_compliance, metrics, planogram_items),
        "placement_compliance": merge_gpt_metric(
            metric_value(metrics.get("placement_compliance_percent"), "available")
            if metrics.get("placement_compliance_percent") is not None
            else not_configured("Placement rules not configured"),
            gpt.get("placement_compliance"),
        ),
        "planogram_analysis": {
            "status": "configured" if planogram_items else "not_configured",
            "sku_match_percent": merge_gpt_metric(
                metric_value(
                    metrics.get("planogram_sku_match_percent") or metrics.get("planogram_compliance_percent"),
                    "available" if planogram_items else "not_configured",
                ),
                (gpt.get("planogram_analysis") or {}).get("sku_match_percent")
                if isinstance(gpt.get("planogram_analysis"), dict)
                else None,
            ),
            "qty_compliance_percent": metric_value(
                metrics.get("planogram_qty_compliance_percent"),
                "available" if planogram_items else "not_configured",
            ),
        },
        "share_of_facings": share_of_facings,
        "linear_shelf_share": not_configured("Shelf geometry not calibrated"),
        "presentability": build_presentability(metrics, inventory),
        "pricing": build_pricing(classified, planogram_items),
        "audit_scope": metrics.get("audit_scope"),
        "adjacent_category_findings": metrics.get("adjacent_category_findings") or [],
        "multi_photo": metrics.get("multi_photo"),
        "promotions": not_configured("Promotion rules not configured"),
        "posm": not_configured("POSM rules not configured"),
        "freshness": not_configured("Freshness rules not configured"),
        "fifo": insufficient("Multiple batch dates not visible"),
        "fefo": insufficient("Multiple batch dates not visible"),
        "product_condition": metric_value(
            sum(1 for row in inventory if row.get("damaged")),
            "insufficient_evidence",
        ),
        "cooler": not_configured("Not a cooler audit") if "cooler" not in str(ctx.get("sub_category", "")).lower() else insufficient(),
        "launch_execution": not_configured("No launch SKUs configured"),
        "retail_execution_score": metrics.get("retail_execution_score")
        if isinstance(metrics.get("retail_execution_score"), dict)
        else {
            "overall": metrics.get("shelf_execution_score"),
            "state": "available" if metrics.get("shelf_execution_score") is not None else "not_configured",
            "components": metrics.get("score_components") or [],
        },
        "financial_impact": metrics.get("financial_impact"),
        "opportunity_ledger": build_opportunity_ledger(metrics, inventory, planogram_compliance, next_best_actions),
        "role_specific_insights": _mode_insights(customer_type, metrics),
        "next_best_actions": next_best_actions,
    }

    for key in ("role_summaries", "competitive_insights", "role_insights"):
        if gpt.get(key):
            intel[key] = gpt[key]

    from app.audit_kpi_engine import compute_role_audit_dashboard
    from app.price_compliance import compute_price_compliance

    planogram_package = (ctx.get("planogram_package") or {}) if isinstance(ctx.get("planogram_package"), dict) else {}
    price_raw = compute_price_compliance(classified, planogram_items)
    intel["audit_kpi_dashboard"] = compute_role_audit_dashboard(
        customer_type=customer_type,
        planogram_items=planogram_items,
        planogram_compliance=planogram_compliance,
        inventory=inventory,
        classified=classified,
        price_compliance=price_raw,
        planogram_package=planogram_package,
        scan_context=ctx,
    )

    return intel
