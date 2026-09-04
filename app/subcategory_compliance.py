"""Detect products that do not match the auditor-selected sub-category."""

from __future__ import annotations

import re
from collections import defaultdict

from app.scan_context import (
    AISLE_DISPLAY_NAMES,
    AISLE_PRODUCT_KEYWORDS,
    COMPLIANCE_ALERT_INTERPRETATION,
    COMPLIANCE_ALERT_TITLE,
    SNACK_AISLE_KEYS,
    SUB_CATEGORY_BRAND_HINTS,
    SUB_CATEGORY_PRODUCT_KEYWORDS,
    aisle_category_matches,
    effective_sub_category,
    foreign_aisle_conflict,
    multi_sub_category_audit,
    resolve_subcategory_label,
    selected_sub_category_ids,
    sku_allowed_in_context,
    sub_categories_match,
    _pc_brand_in_any_subcategory,
)

MIN_COMPLIANCE_CONFIDENCE = 0.5

MOUTHWASH_PRODUCT_KEYWORDS = (
    "mouthwash",
    "mouth wash",
    "oral rinse",
    "plax",
    "listerine",
    "colgate plax",
)


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
    matched: set[str] = set()
    for sub_id, brands in hints.items():
        for hint in brands:
            hint_l = hint.lower()
            if brand_l == hint_l or brand_l in hint_l or hint_l in brand_l:
                matched.add(sub_id)
    return matched


def _keyword_score(haystack: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in haystack)


def _pc_brand_in_context(brand: str, scan_context: dict) -> bool:
    """True when brand belongs to personal care hints for this scan."""
    brand_l = brand.lower().strip()
    if not brand_l:
        return False
    hints = scan_context.get("brand_hints") or set()
    if brand_l in hints:
        return True
    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    if aislix_key != "personal care":
        return False
    for sub_brands in (SUB_CATEGORY_BRAND_HINTS.get("personal care") or {}).values():
        if brand_l in sub_brands:
            return True
        for hint in sub_brands:
            if brand_l in hint or hint in brand_l:
                return True
    return False


def _sibling_pc_subcategory(selected: str, detected: str | None) -> bool:
    """Shampoo vs conditioner on same aisle — not a putaway violation."""
    if not detected or detected == selected:
        return True
    hair_care = {"shampoo", "conditioner"}
    if selected in hair_care and detected in hair_care:
        return True
    return False


def _sibling_chips_subcategory(selected: str, detected: str | None) -> bool:
    """Potato/tortilla/extruded/namkeen facings on a Chips rack audit."""
    from app.scan_context import CHIPS_RACK_SUBCATEGORIES

    if not detected or detected == selected:
        return True
    if selected in CHIPS_RACK_SUBCATEGORIES and detected in CHIPS_RACK_SUBCATEGORIES:
        return True
    return False


def _shampoo_product_text(haystack: str) -> bool:
    """True when label text describes hair wash, not body lotion/skincare."""
    h = haystack.lower()
    if any(
        token in h
        for token in (
            "body lotion",
            "smooth skin lotion",
            "skin lotion",
            "body milk",
            "natural glow",
            "moisturising lotion",
            "moisturizing lotion",
        )
    ):
        return False
    if "shampoo" in h or "conditioner" in h:
        return True
    return any(
        token in h
        for token in ("keratin", "anti dandruff", "hair fall", "hyaluron moisture", "vatika", "cool menthol")
    )


def _subcategory_product_guard(selected: str, haystack: str, pack_text: str = "") -> bool:
    """True when label/pack text clearly belongs to the selected sub-category."""
    if selected == "shampoo" and _shampoo_product_text(haystack):
        return True
    combined = _normalize_key(f"{haystack} {pack_text}")
    keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(selected) or []
    if keywords and _keyword_score(combined, keywords) > 0:
        return True
    return False


def _infer_foreign_aisle(
    haystack: str,
    scan_aisle_key: str,
    scan_context: dict | None = None,
    pack_text: str = "",
) -> tuple[str, str] | None:
    """Return (aisle_key, display_name) when product text belongs to another aisle."""
    if scan_context:
        return foreign_aisle_conflict(haystack, scan_context, pack_text=pack_text)
    haystack_l = haystack.lower()
    tea_on_beverage_scan = (
        scan_aisle_key == "beverages"
        and any(token in haystack_l for token in ("masala chai", "tulsi masala", "tulsi chai", "organic india"))
    )
    if tea_on_beverage_scan:
        return None

    best_score = 0
    best_aisle = ""
    for aisle_key, keywords in AISLE_PRODUCT_KEYWORDS.items():
        if aisle_key == scan_aisle_key:
            continue
        score = _keyword_score(haystack, keywords)
        if score > best_score:
            best_score = score
            best_aisle = aisle_key
    if best_score > 0 and best_aisle:
        if (
            scan_aisle_key == "beverages"
            and best_aisle == "grocery & staples"
            and "masala" in haystack_l
            and _keyword_score(haystack, ["tea", "chai", "tulsi"]) > 0
        ):
            return None
        return best_aisle, AISLE_DISPLAY_NAMES.get(best_aisle, best_aisle.title())
    return None


def infer_detected_subcategory(item: dict, scan_context: dict | None) -> str | None:
    """Best-effort sub-category id for a facing within the scan aisle (None if inconclusive)."""
    if not scan_context:
        return None

    haystack = _haystack(item)
    if len(haystack) < 3:
        return None

    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    aisle_hints = SUB_CATEGORY_BRAND_HINTS.get(aislix_key) or {}
    candidate_ids = set(aisle_hints.keys())

    scored: list[tuple[int, str]] = []
    for sub_id in candidate_ids:
        keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(sub_id) or []
        score = _keyword_score(haystack, keywords)
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


def _snack_aisle_brand_guard(brand: str, scan_context: dict) -> bool:
    """Snack brands on a snack-aisle audit are never cross-aisle violations."""
    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    if aislix_key not in SNACK_AISLE_KEYS:
        return False
    brand_l = brand.lower().strip()
    hints = scan_context.get("brand_hints") or set()
    return brand_l in hints or brand_l in {"lays", "lay's", "kurkure", "bingo", "crax", "pringles", "doritos", "balaji", "tooyumm"}


def _pc_aisle_brand_guard(item: dict, scan_context: dict) -> bool:
    """
    Mixed PC shelves: allow deodorant/skincare/shaving on a shampoo-focused audit
    when the product text clearly belongs to another PC sub-category.
    """
    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    if aislix_key != "personal care":
        return False
    brand = (item.get("brand") or "").strip()
    if not _pc_brand_in_any_subcategory(brand.lower()) and not _pc_brand_in_context(brand, scan_context):
        return False

    selected = effective_sub_category(scan_context) or scan_context.get("sub_category") or ""
    haystack = _haystack(item)
    pack_text = (item.get("pack_text") or "").strip()
    combined = _normalize_key(f"{haystack} {pack_text}")

    if selected == "shampoo" and _shampoo_product_text(combined):
        return False
    if selected == "soap":
        soap_kw = SUB_CATEGORY_PRODUCT_KEYWORDS.get("soap") or []
        if any(kw in combined for kw in soap_kw):
            return False
    if selected == "toothpaste":
        tp_kw = SUB_CATEGORY_PRODUCT_KEYWORDS.get("toothpaste") or []
        if any(kw in combined for kw in tp_kw):
            return False

    sibling_subs = ("deodorant", "skincare", "shaving", "cosmetics", "hand_care")
    for sub_id in sibling_subs:
        if sub_id == selected:
            continue
        keywords = SUB_CATEGORY_PRODUCT_KEYWORDS.get(sub_id) or []
        if keywords and any(kw in combined for kw in keywords):
            return True
    return False


def _evaluate_compliance(
    item: dict,
    scan_context: dict,
    selected: str,
    selected_label: str,
) -> tuple[bool, str, str]:
    """
    Return (is_match, detected_sub_id, detected_label).
    detected_label is human-readable for alerts/CSV.
    """
    haystack = _haystack(item)
    aislix_key = _normalize_key(scan_context.get("aislix_category") or "")
    brand = (item.get("brand") or "").strip()
    pack_text = (item.get("pack_text") or "").strip()
    selected = effective_sub_category(scan_context) or scan_context.get("sub_category") or ""
    selected_all = selected_sub_category_ids(scan_context) or ([selected] if selected else [])

    if _mouthwash_mismatch_on_toothpaste_audit(item, scan_context):
        return False, "mouthwash", "Mouthwash"

    if multi_sub_category_audit(scan_context):
        detected = infer_detected_subcategory(item, scan_context)
        cat_name = scan_context.get("aislix_category")
        if detected and any(
            sub_categories_match(detected, sel, cat_name) for sel in selected_all
        ):
            return True, detected, _subcategory_label(scan_context, detected)
        if _pc_brand_in_any_subcategory(brand.lower().strip()) or _pc_brand_in_context(brand, scan_context):
            guard_sub = detected or selected
            return True, guard_sub, _subcategory_label(scan_context, guard_sub)
        if _snack_aisle_brand_guard(brand, scan_context):
            return True, selected, selected_label

    if _snack_aisle_brand_guard(brand, scan_context):
        return True, selected, selected_label

    if _pc_aisle_brand_guard(item, scan_context):
        return True, selected, selected_label

    if not sku_allowed_in_context(
        brand,
        item.get("sku") or "",
        item.get("category") or "",
        context=scan_context,
    ):
        # Unlisted brands (e.g. Odol, Doctor) still belong when label text matches the audit.
        if _subcategory_product_guard(selected, haystack, pack_text):
            return True, selected, selected_label
        foreign = _infer_foreign_aisle(haystack, aislix_key, scan_context, pack_text)
        if foreign:
            return False, foreign[0], foreign[1]
        return False, "cross_aisle", "Other Aisle"

    allowed_catalog = [c.lower() for c in (scan_context.get("catalog_categories") or [])]
    item_cat = (item.get("category") or "General").strip().lower()
    if aisle_category_matches(item.get("category"), scan_context.get("aislix_category")):
        pass
    elif allowed_catalog and item_cat not in {"", "general"} and item_cat not in allowed_catalog:
        if aislix_key == "personal care" and _pc_brand_in_context(brand, scan_context):
            pass
        elif aislix_key in SNACK_AISLE_KEYS and _snack_aisle_brand_guard(brand, scan_context):
            pass
        else:
            foreign = _infer_foreign_aisle(haystack, aislix_key, scan_context, pack_text)
            label = foreign[1] if foreign else item_cat.title()
            return False, foreign[0] if foreign else "cross_aisle", label

    foreign = _infer_foreign_aisle(haystack, aislix_key, scan_context, pack_text)
    if foreign:
        if _subcategory_product_guard(selected, haystack, pack_text):
            pass
        else:
            return False, foreign[0], foreign[1]

    detected = infer_detected_subcategory(item, scan_context)
    cat_name = scan_context.get("aislix_category")
    if detected and not sub_categories_match(detected, selected, cat_name):
        if _sibling_pc_subcategory(selected, detected):
            return True, selected, selected_label
        if _sibling_chips_subcategory(selected, detected):
            return True, selected, selected_label
        pack_text = (item.get("pack_text") or "").strip()
        if _subcategory_product_guard(selected, haystack, pack_text):
            return True, selected, selected_label
        return False, detected, _subcategory_label(scan_context, detected)

    if not detected:
        brand_subs = _brand_subcategories(aislix_key, brand)
        if selected in brand_subs:
            return True, selected, selected_label
        if len(brand_subs) == 1 and selected not in brand_subs:
            other = next(iter(brand_subs))
            return False, other, _subcategory_label(scan_context, other)

    return True, selected, selected_label


def _subcategory_label(scan_context: dict, sub_id: str) -> str:
    from app.scan_context import resolve_aislix_category

    if sub_id in AISLE_DISPLAY_NAMES:
        return AISLE_DISPLAY_NAMES[sub_id]
    if sub_id == "cross_aisle":
        return "Other Aisle"
    category = resolve_aislix_category(scan_context.get("aislix_category") or "")
    return resolve_subcategory_label(category, sub_id) or sub_id.replace("_", " ").title()


def _is_mouthwash_product(haystack: str, pack_text: str = "") -> bool:
    combined = _normalize_key(f"{haystack} {pack_text}")
    if not any(kw in combined for kw in MOUTHWASH_PRODUCT_KEYWORDS):
        return False
    if "toothpaste" in combined and not any(
        kw in combined for kw in ("mouthwash", "mouth wash", "plax", "listerine")
    ):
        return False
    return True


def _mouthwash_mismatch_on_toothpaste_audit(item: dict, scan_context: dict) -> bool:
    selected = effective_sub_category(scan_context) or scan_context.get("sub_category") or ""
    if selected != "toothpaste":
        return False
    haystack = _haystack(item)
    pack_text = (item.get("pack_text") or "").strip()
    product_l = _normalize_key(item.get("product_name") or "")
    if _is_mouthwash_product(haystack, pack_text):
        return True
    return product_l == "mouthwash"


def _unknown_brand_has_foreign_product_text(item: dict, scan_context: dict) -> bool:
    """True when readable label text clearly belongs outside the audit sub-category."""
    haystack = _haystack(item)
    pack_text = (item.get("pack_text") or "").strip()
    selected = effective_sub_category(scan_context) or scan_context.get("sub_category") or ""
    if _mouthwash_mismatch_on_toothpaste_audit(item, scan_context):
        return True
    if _subcategory_product_guard(selected, haystack, pack_text):
        return False
    return foreign_aisle_conflict(haystack, scan_context, pack_text=pack_text) is not None


def _planogram_label_trusted_for_audit(item: dict, scan_context: dict) -> bool:
    """Closed-vocabulary planogram labels are on-assignment — skip cross-aisle mismatch."""
    if not item.get("planogram_guided"):
        return False
    if not scan_context.get("planogram_candidates") and not scan_context.get("planogram_mode"):
        return False
    brand = (item.get("brand") or "").strip().lower()
    product = (item.get("product_name") or "").strip().lower()
    if brand in {"", "unknown", "n/a"}:
        return False
    if product in {"", "unknown", "unidentified sku", "n/a"}:
        return False
    return True


def analyze_subcategory_compliance(
    classified: list[dict],
    scan_context: dict | None,
) -> dict:
    """
    Flag facings whose inferred sub-category or aisle differs from the audit selection.
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
            if not _unknown_brand_has_foreign_product_text(item, scan_context):
                item["subcategory_match"] = True
                continue
        if float(item.get("confidence") or 0) < MIN_COMPLIANCE_CONFIDENCE:
            item["subcategory_match"] = True
            continue

        if _planogram_label_trusted_for_audit(item, scan_context):
            item["subcategory_match"] = True
            item["expected_sub_category"] = selected
            continue

        is_match, detected_id, detected_label = _evaluate_compliance(
            item, scan_context, selected, selected_label
        )
        if not is_match:
            pack_text = (item.get("pack_text") or "").strip()
            if pack_text:
                from app.brand_dictionary import match_from_text, category_allows_brand

                ocr_label = match_from_text(pack_text, scan_context=scan_context)
                brand = (ocr_label or {}).get("brand") or ""
                product = (ocr_label or {}).get("product_name") or ""
                if (
                    ocr_label
                    and brand.strip()
                    and product.strip()
                    and brand.lower() not in {"unknown", "n/a"}
                    and category_allows_brand(
                        None,
                        brand,
                        ocr_label.get("sku") or "",
                        ocr_label.get("category") or "",
                        scan_context=scan_context,
                    )
                ):
                    probe = dict(item)
                    probe.update(ocr_label)
                    retry_match, retry_id, retry_label = _evaluate_compliance(
                        probe, scan_context, selected, selected_label
                    )
                    if retry_match:
                        item.update(ocr_label)
                        item["recognition_source"] = "ocr+compliance"
                        is_match = True
                        detected_id = retry_id
                        detected_label = retry_label

        if is_match:
            item["subcategory_match"] = True
            item["expected_sub_category"] = selected
            continue

        item["subcategory_match"] = False
        item["compliance_issue"] = "wrong_subcategory"
        item["expected_sub_category"] = selected
        item["expected_sub_category_label"] = selected_label
        item["detected_sub_category"] = detected_id
        item["detected_sub_category_label"] = detected_label
        misplaced += 1

        key = (
            (item.get("brand") or "").strip(),
            (item.get("product_name") or "").strip(),
            detected_id,
        )
        bucket = mismatch_buckets[key]
        bucket["brand"] = key[0]
        bucket["product_name"] = key[1]
        bucket["detected_sub_category"] = detected_id
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
                    f"categories or sub-categories — {breakdown}."
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
