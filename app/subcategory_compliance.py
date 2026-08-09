"""Detect products that do not match the auditor-selected sub-category."""

from __future__ import annotations

import re
from collections import defaultdict

from app.scan_context import (
    COMPLIANCE_ALERT_INTERPRETATION,
    COMPLIANCE_ALERT_TITLE,
    SUB_CATEGORY_BRAND_HINTS,
    SUB_CATEGORY_PRODUCT_KEYWORDS,
    resolve_subcategory_label,
)

MIN_COMPLIANCE_CONFIDENCE = 0.5


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _haystack(item: dict) -> str:
    parts = [
        item.get("brand") or "",
        item.get("product_name") or "",
        item.get("variant") or "",
    ]
    return _normalize_key(" ".join(p for p in parts if p))


def _brand_subcategories(aislix_key: str, brand: str) -> set[str]:
    brand_l = brand.lower().strip()
    if not brand_l or brand_l == "unknown":
        return set()
    hints = SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}
    return {sub_id for sub_id, brands in hints.items() if brand_l in brands}


def _keyword_score(haystack: str, sub_id: str) -> int:
    keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(sub_id) or []
    return sum(1 for kw in keywords if kw in haystack)


def infer_detected_subcategory(item: dict, scan_context: dict | None) -> str | None:
    """Best-effort sub-category id for a facing (None if inconclusive)."""
    if not scan_context:
        return None

    haystack = _haystack(item)
    if len(haystack) < 3:
        return None

    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    aisle_hints = SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}
    candidate_ids = set(aisle_hints.keys()) | set(SUB_CATEGORY_PRODUCT_KEYWORDS.keys())

    scored: list[tuple[int, str]] = []
    for sub_id in candidate_ids:
        score = _keyword_score(haystack, sub_id)
        if score > 0:
            scored.append((score, sub_id))

    if scored:
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return scored[0][1]

    brand = (item.get("brand") or "").strip()
    brand_subs = _brand_subcategories(aislix_key, brand)
    if len(brand_subs) == 1:
        return next(iter(brand_subs))
    return None


def _subcategory_label(scan_context: dict, sub_id: str) -> str:
    from app.scan_context import resolve_aislix_category

    category = resolve_aislix_category(scan_context.get("aislix_category") or "")
    return resolve_subcategory_label(category, sub_id) or sub_id.replace("_", " ").title()


def analyze_subcategory_compliance(
    classified: list[dict],
    scan_context: dict | None,
) -> dict:
    """
    Flag facings whose inferred sub-category differs from the audit selection.
    Returns updated classified list, aggregated mismatches, and compliance alerts.
    """
    empty = {
        "classified": classified,
        "subcategory_mismatches": [],
        "compliance_alerts": [],
        "misplaced_facings": 0,
    }
    if not scan_context:
        return empty

    selected = scan_context.get("sub_category")
    if not selected or selected == "others":
        return empty

    selected_label = (
        scan_context.get("sub_category_label")
        or scan_context.get("sub_category_custom")
        or selected.replace("_", " ").title()
    )

    mismatch_buckets: dict[tuple, dict] = defaultdict(
        lambda: {
            "quantity": 0,
            "confidences": [],
            "boxes": [],
        }
    )
    misplaced = 0

    for item in classified:
        brand_l = (item.get("brand") or "").strip().lower()
        if brand_l in {"", "unknown"}:
            item["subcategory_match"] = True
            continue
        if float(item.get("confidence") or 0) < MIN_COMPLIANCE_CONFIDENCE:
            item["subcategory_match"] = True
            continue

        detected = infer_detected_subcategory(item, scan_context)
        if not detected or detected == selected:
            item["subcategory_match"] = True
            item["expected_sub_category"] = selected
            continue

        detected_label = _subcategory_label(scan_context, detected)
        item["subcategory_match"] = False
        item["compliance_issue"] = "wrong_subcategory"
        item["expected_sub_category"] = selected
        item["expected_sub_category_label"] = selected_label
        item["detected_sub_category"] = detected
        item["detected_sub_category_label"] = detected_label
        misplaced += 1

        key = (
            (item.get("brand") or "").strip(),
            (item.get("product_name") or "").strip(),
            detected,
        )
        bucket = mismatch_buckets[key]
        bucket["brand"] = key[0]
        bucket["product_name"] = key[1]
        bucket["detected_sub_category"] = detected
        bucket["detected_sub_category_label"] = detected_label
        bucket["expected_sub_category"] = selected
        bucket["expected_sub_category_label"] = selected_label
        bucket["quantity"] += 1
        bucket["confidences"].append(float(item.get("confidence") or 0))
        if "x1" in item:
            bucket["boxes"].append(
                {"x1": item["x1"], "y1": item["y1"], "x2": item["x2"], "y2": item["y2"]}
            )

    mismatches = []
    for bucket in mismatch_buckets.values():
        avg_conf = sum(bucket["confidences"]) / max(len(bucket["confidences"]), 1)
        mismatches.append(
            {
                "brand": bucket["brand"],
                "product_name": bucket["product_name"],
                "detected_sub_category": bucket["detected_sub_category"],
                "detected_sub_category_label": bucket["detected_sub_category_label"],
                "expected_sub_category": bucket["expected_sub_category"],
                "expected_sub_category_label": bucket["expected_sub_category_label"],
                "quantity": bucket["quantity"],
                "confidence": round(avg_conf, 4),
                "boxes": bucket["boxes"],
            }
        )
    mismatches.sort(key=lambda row: row["quantity"], reverse=True)

    compliance_alerts: list[dict] = []
    if misplaced > 0:
        by_detected: dict[str, int] = defaultdict(int)
        for row in mismatches:
            by_detected[row["detected_sub_category_label"]] += row["quantity"]
        breakdown = ", ".join(
            f"{label} ({qty})" for label, qty in sorted(by_detected.items(), key=lambda x: -x[1])
        )
        compliance_alerts.append(
            {
                "id": "category-mismatch",
                "severity": "high" if misplaced > 5 else "medium",
                "category": "compliance",
                "title": COMPLIANCE_ALERT_TITLE,
                "interpretation": COMPLIANCE_ALERT_INTERPRETATION,
                "detail": (
                    f"{selected_label} audit: {misplaced} facing(s) appear to belong to other "
                    f"sub-categories — {breakdown}."
                ),
                "expected_sub_category": selected,
                "expected_sub_category_label": selected_label,
                "misplaced_facings": misplaced,
                "mismatch_groups": len(mismatches),
            }
        )

    return {
        "classified": classified,
        "subcategory_mismatches": mismatches,
        "compliance_alerts": compliance_alerts,
        "misplaced_facings": misplaced,
    }


def apply_compliance_to_inventory(
    inventory: list[dict],
    mismatches: list[dict],
) -> list[dict]:
    """Mark inventory rows that include at least one mismatched facing."""
    mismatch_by_product: dict[tuple[str, str], dict] = {}
    for row in mismatches:
        key = (
            (row.get("brand") or "").lower(),
            (row.get("product_name") or "").lower(),
        )
        mismatch_by_product[key] = row

    for row in inventory:
        key = (
            (row.get("brand") or "").lower(),
            (row.get("product_name") or "").lower(),
        )
        mismatch = mismatch_by_product.get(key)
        if mismatch:
            row["compliance_status"] = "category_mismatch"
            row["compliance_alert"] = COMPLIANCE_ALERT_TITLE
            row["compliance_interpretation"] = COMPLIANCE_ALERT_INTERPRETATION
            row["detected_sub_category"] = mismatch.get("detected_sub_category")
            row["detected_sub_category_label"] = mismatch.get("detected_sub_category_label")
            row["expected_sub_category"] = mismatch.get("expected_sub_category")
            row["expected_sub_category_label"] = mismatch.get("expected_sub_category_label")
        else:
            row["compliance_status"] = "ok"
            row["compliance_alert"] = "OK"
            row["compliance_interpretation"] = ""
    return inventory
