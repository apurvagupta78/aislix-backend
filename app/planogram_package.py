"""Build a unified planogram audit package from product rows + optional stored package."""

from __future__ import annotations

from typing import Any


def _sku(row: dict) -> str:
    return str(row.get("sku") or row.get("match_key") or "").strip()


def _brand(row: dict) -> str:
    return str(row.get("brand") or "").strip()


def synthesize_planogram_package(
    planogram_items: list[dict] | None,
    audit_package: dict | None = None,
    *,
    primary_brand: str | None = None,
    store_timezone: str | None = None,
) -> dict[str, Any]:
    """
    Merge stored audit_package with product rows so every KPI has reference data.
    Product rows always supply listed_skus; missing lists/prices are derived from rows.
    """
    items = list(planogram_items or [])
    pkg = dict(audit_package or {})
    out: dict[str, Any] = {}

    out["listed_skus"] = items

    if pkg.get("assortment_skus"):
        out["assortment_skus"] = list(pkg["assortment_skus"])
    else:
        out["assortment_skus"] = [
            {
                "sku": _sku(row),
                "list_type": "mandatory_assortment",
                "outlet_scope": "all",
            }
            for row in items
            if _sku(row)
        ]

    if pkg.get("msl_skus"):
        out["msl_skus"] = list(pkg["msl_skus"])
    elif pkg.get("must_stock_skus"):
        out["msl_skus"] = list(pkg["must_stock_skus"])
    else:
        out["msl_skus"] = [
            {
                "sku": _sku(row),
                "list_type": "msl",
                "outlet_scope": str(row.get("location") or "all"),
            }
            for row in items
            if _sku(row) and row.get("is_msl")
        ]

    if pkg.get("price_requirements"):
        out["price_requirements"] = list(pkg["price_requirements"])
    else:
        prices = []
        for row in items:
            sku = _sku(row)
            mrp = row.get("mrp_inr") or row.get("authorized_shelf_price")
            if not sku or mrp in (None, ""):
                continue
            try:
                price = float(mrp)
            except (TypeError, ValueError):
                continue
            prices.append(
                {
                    "sku": sku,
                    "label_location": str(row.get("shelf_position") or "shelf_tag"),
                    "expected_price": price,
                    "currency": "INR",
                    "price_basis": str(row.get("price_basis") or "item"),
                }
            )
        out["price_requirements"] = prices

    out["promotions"] = list(pkg.get("promotions") or [])
    out["promotion_results"] = list(pkg.get("promotion_results") or [])
    out["scoring"] = dict(pkg.get("scoring") or {})

    brand = (
        str(pkg.get("primary_brand") or "").strip()
        or str(primary_brand or "").strip()
    )
    if not brand and items:
        counts: dict[str, int] = {}
        for row in items:
            b = _brand(row)
            if b:
                counts[b] = counts.get(b, 0) + 1
        if counts:
            brand = max(counts, key=counts.get)
    if brand:
        out["primary_brand"] = brand

    out["fixture_id"] = pkg.get("fixture_id") or (items[0].get("location") if items else None)
    out["store_timezone"] = pkg.get("store_timezone") or store_timezone or "Asia/Kolkata"

    geometry = pkg.get("sos_geometry")
    if isinstance(geometry, dict) and geometry:
        out["sos_geometry"] = geometry
    elif brand:
        out["sos_geometry"] = {
            "calibrated": False,
            "basis": "bbox_width_proxy",
            "category_boundary": items[0].get("category") if items else None,
        }

    return out
