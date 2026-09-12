"""Assemble role-specific five-KPI dashboard from scan evidence and planogram package."""

from __future__ import annotations

from typing import Any

from app.audit_kpi_calculators import (
    compute_assortment_compliance,
    compute_facing_count,
    compute_location_accuracy,
    compute_msl_compliance,
    compute_osa,
    compute_planogram_compliance,
    compute_price_compliance,
    compute_promotional_compliance,
    compute_share_of_shelf,
    not_configured_kpi,
)
from app.kpi_result import KpiResult
from app.role_kpi_config import ROLE_PROFILES, get_role_profile, normalize_role_id


def _match_key(item: dict) -> str:
    return str(item.get("match_key") or "").strip().lower() or (
        f"{str(item.get('brand') or '').strip().lower()}|{str(item.get('product_name') or item.get('product') or '').strip().lower()}"
    )


def _expected_facings(item: dict) -> int | None:
    raw = item.get("expected_facings")
    if raw not in (None, ""):
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    raw_qty = item.get("expected_qty")
    if raw_qty not in (None, ""):
        try:
            return max(0, int(raw_qty))
        except (TypeError, ValueError):
            pass
    return None


def _inventory_by_key(inventory: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in inventory:
        key = _match_key(row)
        if key:
            out[key] = row
    return out


def _osa_units(
    listed_skus: list[dict],
    inventory_by_key: dict[str, dict],
    compliance_lines: list[dict] | None,
) -> list[dict]:
    line_by_id = {str(l.get("planogram_item_id") or ""): l for l in (compliance_lines or [])}
    units: list[dict] = []
    for sku in listed_skus:
        key = _match_key(sku)
        line = line_by_id.get(str(sku.get("id") or ""))
        issue = (line or {}).get("issue_type")
        inv = inventory_by_key.get(key)
        qty = int((inv or {}).get("quantity") or (inv or {}).get("facings") or 0)
        if issue == "missing":
            state = "fail"
        elif issue in ("wrong_product", "wrong_category", "wrong_location"):
            state = "pass" if qty > 0 else "fail"
        elif qty > 0:
            state = "pass"
        elif line is None and not inv:
            state = "not_assessable"
        else:
            state = "fail"
        units.append({"id": key, "state": state})
    return units


def _planogram_position_units(compliance_lines: list[dict] | None) -> list[dict]:
    units: list[dict] = []
    for line in compliance_lines or []:
        issue = line.get("issue_type")
        if issue in (None, ""):
            units.append({"state": "not_assessable"})
        elif issue == "correct":
            units.append({"state": "pass"})
        elif issue in ("missing", "wrong_product", "wrong_category", "wrong_location", "qty_mismatch", "unexpected"):
            units.append({"state": "fail"})
        else:
            units.append({"state": "needs_review"})
    return units


def _assortment_units(
    assortment_skus: list[dict] | None,
    inventory_by_key: dict[str, dict],
    planogram_items: list[dict] | None,
) -> list[dict]:
    source = assortment_skus if assortment_skus else (planogram_items or [])
    if not source:
        return []
    units: list[dict] = []
    for sku in source:
        if sku.get("optional"):
            continue
        key = _match_key(sku)
        inv = inventory_by_key.get(key)
        qty = int((inv or {}).get("quantity") or (inv or {}).get("facings") or 0)
        if not key:
            units.append({"state": "not_assessable"})
        elif qty > 0:
            units.append({"state": "pass"})
        else:
            units.append({"state": "fail"})
    return units


def _msl_units(
    msl_skus: list[dict] | None,
    inventory_by_key: dict[str, dict],
) -> list[dict]:
    if not msl_skus:
        return []
    units: list[dict] = []
    for sku in msl_skus:
        key = _match_key(sku)
        inv = inventory_by_key.get(key)
        qty = int((inv or {}).get("quantity") or (inv or {}).get("facings") or 0)
        if qty > 0:
            units.append({"state": "pass"})
        else:
            units.append({"state": "fail"})
    return units


def _price_units(price_compliance: dict | None) -> list[dict]:
    if not price_compliance or price_compliance.get("state") == "not_configured":
        return []
    units: list[dict] = []
    for line in price_compliance.get("lines") or []:
        status = line.get("status")
        if status == "compliant":
            units.append({"state": "pass"})
        elif status in ("non_compliant", "mismatch"):
            units.append({"state": "fail"})
        else:
            units.append({"state": "not_assessable"})
    return units


def _promo_units(promotions: list[dict] | None, promo_results: list[dict] | None) -> tuple[list[dict], int]:
    promos = promotions or []
    if not promos:
        return [], 0
    result_by_id = {str(r.get("promotion_id") or ""): r for r in (promo_results or [])}
    units: list[dict] = []
    for promo in promos:
        pid = str(promo.get("promotion_id") or promo.get("id") or "")
        res = result_by_id.get(pid) or {}
        status = res.get("status") or promo.get("status")
        if status == "pass":
            units.append({"state": "pass"})
        elif status == "fail":
            units.append({"state": "fail"})
        elif status == "not_assessable":
            units.append({"state": "not_assessable"})
        else:
            units.append({"state": "not_assessable"})
    return units, len(promos)


def _location_units(compliance_lines: list[dict] | None) -> list[dict]:
    units: list[dict] = []
    for line in compliance_lines or []:
        issue = line.get("issue_type")
        actual_qty = int(line.get("actual_qty") or 0)
        if actual_qty <= 0:
            continue
        if issue in ("wrong_product", "wrong_location", "wrong_category"):
            units.append({"state": "fail"})
        elif issue == "correct":
            units.append({"state": "pass"})
        elif issue == "qty_mismatch":
            units.append({"state": "pass"})
        else:
            units.append({"state": "not_assessable"})
    return units


def _facing_totals(
    planogram_items: list[dict] | None,
    inventory_by_key: dict[str, dict],
    *,
    brand_filter: str | None = None,
) -> tuple[int, int, int, int]:
    actual = 0
    planned = 0
    assessed = 0
    eligible = 0
    brand_norm = (brand_filter or "").strip().lower()
    for item in planogram_items or []:
        if brand_norm and str(item.get("brand") or "").strip().lower() != brand_norm:
            continue
        expected = _expected_facings(item)
        if expected is None:
            continue
        eligible += 1
        key = _match_key(item)
        inv = inventory_by_key.get(key)
        observed = int((inv or {}).get("facings") or (inv or {}).get("quantity") or 0)
        if inv is not None:
            assessed += 1
        actual += observed
        planned += expected
    return actual, planned, assessed, eligible


def _linear_sos(
    classified: list[dict],
    *,
    primary_brand: str | None,
    category_scope: str | None = None,
) -> tuple[float, float, bool]:
    brand_norm = (primary_brand or "").strip().lower()
    if not brand_norm or not classified:
        return 0.0, 0.0, False

    def width(row: dict) -> float:
        try:
            return max(0.0, float(row.get("x2", 0)) - float(row.get("x1", 0)))
        except (TypeError, ValueError):
            return 0.0

    total = 0.0
    brand = 0.0
    for row in classified:
        if category_scope:
            sub = str(row.get("sub_category") or row.get("category") or "").lower()
            if category_scope.lower() not in sub:
                continue
        w = width(row)
        if w <= 0:
            continue
        total += w
        if str(row.get("brand") or "").strip().lower() == brand_norm:
            brand += w
    return brand, total, total > 0


def _compute_single_kpi(
    kpi_id: str,
    *,
    scope: str,
    role_id: str,
    planogram_items: list[dict] | None,
    planogram_compliance: dict | None,
    inventory: list[dict],
    classified: list[dict],
    price_compliance: dict | None,
    planogram_package: dict | None,
    primary_brand: str | None,
    category_scope: str | None,
) -> KpiResult:
    package = planogram_package or {}
    inventory_by_key = _inventory_by_key(inventory)
    lines = (planogram_compliance or {}).get("lines") or []
    listed = planogram_items or package.get("listed_skus") or []

    if kpi_id == "osa":
        if not listed:
            return not_configured_kpi("osa", "On-Shelf Availability (OSA)", scope=scope)
        units = _osa_units(listed, inventory_by_key, lines)
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = sum(1 for u in units if u["state"] != "not_assessable")
        return compute_osa(
            listed_available=passing,
            listed_assessed=assessed,
            listed_eligible=len(units),
            scope=scope,
        )

    if kpi_id == "planogram_compliance":
        if not planogram_items:
            return not_configured_kpi("planogram_compliance", "Planogram Compliance", scope=scope)
        units = _planogram_position_units(lines)
        if not units:
            units = [{"state": "not_assessable"} for _ in planogram_items]
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = sum(1 for u in units if u["state"] != "not_assessable")
        return compute_planogram_compliance(
            positions_passing=passing,
            positions_assessed=assessed,
            positions_eligible=len(units),
            scope=scope,
        )

    if kpi_id == "assortment_compliance":
        assortment = package.get("assortment_skus") or package.get("mandatory_assortment")
        units = _assortment_units(assortment, inventory_by_key, planogram_items)
        if not units:
            return not_configured_kpi("assortment_compliance", "Assortment Compliance", scope=scope)
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = sum(1 for u in units if u["state"] != "not_assessable")
        return compute_assortment_compliance(
            present_required=passing,
            assessed_required=assessed,
            eligible_required=len(units),
            scope=scope,
        )

    if kpi_id == "price_compliance":
        units = _price_units(price_compliance)
        if not units:
            has_prices = any(item.get("mrp_inr") not in (None, "") for item in (planogram_items or []))
            if not has_prices:
                return not_configured_kpi("price_compliance", "Price Compliance", scope=scope)
            return KpiResult(
                kpi_id="price_compliance",
                label="Price Compliance",
                value=None,
                status="not_assessable",
                scope=scope,
                warnings=["Price requirements configured but no readable labels detected."],
            )
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = sum(1 for u in units if u["state"] != "not_assessable")
        return compute_price_compliance(
            labels_passing=passing,
            labels_assessed=assessed,
            labels_eligible=len(units),
            scope=scope,
        )

    if kpi_id == "promotional_compliance":
        promos = package.get("promotions") or []
        promo_results = package.get("promotion_results") or []
        units, active = _promo_units(promos, promo_results)
        if not promos:
            return compute_promotional_compliance(
                promotions_passing=0,
                promotions_assessed=0,
                promotions_eligible=0,
                scope=scope,
                active_promotions=0,
            )
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = sum(1 for u in units if u["state"] != "not_assessable")
        return compute_promotional_compliance(
            promotions_passing=passing,
            promotions_assessed=assessed,
            promotions_eligible=len(units),
            scope=scope,
            active_promotions=active,
        )

    if kpi_id == "location_accuracy":
        if not planogram_items or not any(str(i.get("shelf_position") or "").strip() for i in planogram_items):
            return not_configured_kpi(
                "location_accuracy",
                "Location Accuracy",
                scope=scope,
                tooltip="Requires identifiable pick locations or shelf_position mapping.",
            )
        units = _location_units(lines)
        if not units:
            return KpiResult(
                kpi_id="location_accuracy",
                label="Location Accuracy",
                value=None,
                status="not_assessable",
                scope=scope,
            )
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = len(units)
        return compute_location_accuracy(
            locations_correct=passing,
            locations_assessed=assessed,
            locations_eligible=assessed,
            scope=scope,
        )

    if kpi_id == "facing_count":
        if not planogram_items or not any(_expected_facings(i) is not None for i in planogram_items):
            return not_configured_kpi("facing_count", "Facing Count", scope=scope)
        brand = primary_brand if role_id == "fmcg" else None
        actual, planned, assessed, eligible = _facing_totals(
            planogram_items, inventory_by_key, brand_filter=brand
        )
        return compute_facing_count(
            actual_facings=actual,
            planned_facings=planned or None,
            positions_assessed=assessed,
            positions_eligible=eligible,
            scope=scope,
            partial_coverage=eligible > 0 and assessed < eligible,
        )

    if kpi_id == "share_of_shelf":
        brand = primary_brand or (package.get("primary_brand") if package else None)
        brand_w, total_w, ok = _linear_sos(classified, primary_brand=brand, category_scope=category_scope)
        geometry = package.get("sos_geometry") if package else None
        calibrated = bool(geometry and geometry.get("calibrated")) or ok
        return compute_share_of_shelf(
            brand_linear_cm=brand_w,
            total_linear_cm=total_w,
            scope=scope,
            calibrated=calibrated,
            measurement_basis=str((geometry or {}).get("basis") or "bbox_width_proxy"),
        )

    if kpi_id == "msl_compliance":
        msl = package.get("msl_skus") or package.get("must_stock_skus")
        units = _msl_units(msl, inventory_by_key)
        if not units:
            return not_configured_kpi("msl_compliance", "Must-Stock List (MSL) Compliance", scope=scope)
        passing = sum(1 for u in units if u["state"] == "pass")
        assessed = len(units)
        return compute_msl_compliance(
            present_msl=passing,
            assessed_msl=assessed,
            eligible_msl=len(units),
            scope=scope,
        )

    return not_configured_kpi(kpi_id, kpi_id.replace("_", " ").title(), scope=scope)


def compute_role_audit_dashboard(
    *,
    customer_type: str | None,
    planogram_items: list[dict] | None,
    planogram_compliance: dict | None,
    inventory: list[dict],
    classified: list[dict],
    price_compliance: dict | None = None,
    planogram_package: dict | None = None,
    scan_context: dict | None = None,
) -> dict[str, Any]:
    """Return role profile + exactly five primary KPI results."""
    ctx = scan_context or {}
    profile = get_role_profile(customer_type)
    role_id = profile["role_id"]
    scope_parts = [
        str(ctx.get("store_id") or "").strip(),
        str(ctx.get("category") or "").strip(),
        str(ctx.get("sub_category") or "").strip(),
    ]
    scope = " · ".join(p for p in scope_parts if p) or "audit_scope"

    kpis: list[dict] = []
    for definition in profile["primary_kpis"]:
        result = _compute_single_kpi(
            definition["kpi_id"],
            scope=scope,
            role_id=role_id,
            planogram_items=planogram_items,
            planogram_compliance=planogram_compliance,
            inventory=inventory,
            classified=classified,
            price_compliance=price_compliance,
            planogram_package=planogram_package,
            primary_brand=ctx.get("primary_brand"),
            category_scope=ctx.get("sub_category") or ctx.get("category"),
        )
        payload = result.to_dict()
        payload["tooltip"] = definition.get("tooltip") or payload.get("tooltip") or ""
        kpis.append(payload)

    readiness = _readiness_checklist(planogram_items, planogram_package, price_compliance)

    return {
        "role_id": profile["role_id"],
        "role_label": profile["label"],
        "introduction": profile["introduction"],
        "primary_kpis": kpis,
        "kpi_count": len(kpis),
        "readiness": readiness,
        "formula_version": "audit-kpi-v1",
    }


def _readiness_checklist(
    planogram_items: list[dict] | None,
    planogram_package: dict | None,
    price_compliance: dict | None,
) -> list[dict[str, Any]]:
    package = planogram_package or {}
    items = planogram_items or []
    checks = [
        ("osa", bool(items), "Listed SKUs / planogram rows"),
        ("planogram_compliance", bool(items), "Shelf layout positions"),
        ("assortment_compliance", bool(package.get("assortment_skus") or items), "Mandatory assortment list"),
        ("price_compliance", bool(any(i.get("mrp_inr") not in (None, "") for i in items)), "Price requirements"),
        ("promotional_compliance", bool(package.get("promotions")), "Active promotions"),
        ("location_accuracy", bool(any(str(i.get("shelf_position") or "").strip() for i in items)), "Location/slot IDs"),
        ("facing_count", bool(any(_expected_facings(i) is not None for i in items)), "Expected facings"),
        ("share_of_shelf", bool(package.get("sos_geometry") or package.get("primary_brand")), "SOS geometry / brand scope"),
        ("msl_compliance", bool(package.get("msl_skus")), "Must-stock list"),
    ]
    return [{"kpi_id": kid, "ready": ready, "label": label} for kid, ready, label in checks]


def compute_all_role_audit_dashboards(
    *,
    planogram_items: list[dict] | None,
    planogram_compliance: dict | None,
    inventory: list[dict],
    classified: list[dict],
    price_compliance: dict | None = None,
    planogram_package: dict | None = None,
    scan_context: dict | None = None,
) -> dict[str, dict[str, Any]]:
    """Deterministic KPI dashboards for all five customer roles (tab switching)."""
    out: dict[str, dict[str, Any]] = {}
    for role_id in ROLE_PROFILES:
        out[role_id] = compute_role_audit_dashboard(
            customer_type=role_id,
            planogram_items=planogram_items,
            planogram_compliance=planogram_compliance,
            inventory=inventory,
            classified=classified,
            price_compliance=price_compliance,
            planogram_package=planogram_package,
            scan_context=scan_context,
        )
    return out
