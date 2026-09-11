"""CSV templates and parsers for planogram audit package supplements."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from app.planogram_csv import _normalize_header, parse_csv_text


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


ASSORTMENT_HEADERS = "sku,list_type,outlet_scope,valid_from,valid_to,substitution_allowed"
PRICE_HEADERS = "sku,label_location,expected_price,currency,price_basis,valid_from,valid_to"
PROMOTION_HEADERS = (
    "promotion_id,participating_skus,start_date,end_date,required_location,"
    "expected_offer_text,expected_promo_price,required_facings"
)


def template_csv(kind: str) -> dict[str, str]:
    examples = {
        "assortment": (
            f"{ASSORTMENT_HEADERS}\n"
            "COL-MAX-150,mandatory_assortment,all,2026-01-01,2026-12-31,false\n"
            "PEP-GER-150,msl,outlet_a,2026-01-01,2026-12-31,false\n"
        ),
        "prices": (
            f"{PRICE_HEADERS}\n"
            "COL-MAX-150,shelf_tag,99,INR,item,2026-01-01,2026-12-31\n"
            "PEP-GER-150,shelf_tag,75,INR,item,2026-01-01,2026-12-31\n"
        ),
        "promotions": (
            f"{PROMOTION_HEADERS}\n"
            'PROMO-01,"COL-MAX-150|COL-VW-100",2026-03-01,2026-03-31,S1,Buy 2 Save 10%,89,4\n'
        ),
    }
    if kind not in examples:
        raise ValueError(f"Unknown template kind: {kind}")
    return {"header": examples[kind].split("\n")[0], "csv_text": examples[kind]}


def parse_assortment_csv(content: str) -> dict[str, Any]:
    return _parse_simple_csv(content, required=("sku", "list_type"), row_parser=_normalize_assortment_row)


def parse_prices_csv(content: str) -> dict[str, Any]:
    return _parse_simple_csv(content, required=("sku", "expected_price"), row_parser=_normalize_price_row)


def parse_promotions_csv(content: str) -> dict[str, Any]:
    return _parse_simple_csv(content, required=("promotion_id", "participating_skus"), row_parser=_normalize_promotion_row)


def _parse_simple_csv(
    content: str,
    *,
    required: tuple[str, ...],
    row_parser,
) -> dict[str, Any]:
    if not content or not content.strip():
        return {"rows": [], "errors": ["CSV is empty"], "valid_count": 0, "error_count": 0}

    content = content.lstrip("\ufeff")
    sample = content[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        return {"rows": [], "errors": ["Missing header row"], "valid_count": 0, "error_count": 0}

    field_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    header_errors = [f"Missing required column: {col}" for col in required if col not in field_map]
    if header_errors:
        return {"rows": [], "errors": header_errors, "valid_count": 0, "error_count": len(header_errors)}

    rows: list[dict] = []
    all_errors: list[str] = []
    valid_count = 0
    for idx, raw in enumerate(reader, start=2):
        mapped = {canon: raw.get(original, "") for canon, original in field_map.items()}
        normalized, row_errors = row_parser(mapped, row_num=idx)
        if row_errors:
            all_errors.extend(row_errors)
            rows.append({"row_num": idx, "valid": False, "errors": row_errors, "raw": mapped})
        else:
            valid_count += 1
            rows.append({"row_num": idx, "valid": True, "data": normalized})
    return {
        "rows": rows,
        "errors": all_errors,
        "valid_count": valid_count,
        "error_count": len(all_errors),
        "delimiter": delimiter,
    }


def _normalize_assortment_row(row: dict, row_num: int = 0) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    prefix = f"Row {row_num}: " if row_num else ""
    sku = _clean(row.get("sku"))
    list_type = _clean(row.get("list_type")).lower()
    if not sku:
        errors.append(f"{prefix}sku is required")
    if list_type not in ("mandatory_assortment", "msl", "optional"):
        errors.append(f"{prefix}list_type must be mandatory_assortment, msl, or optional")
    if errors:
        return None, errors
    return {
        "sku": sku,
        "list_type": list_type,
        "outlet_scope": _clean(row.get("outlet_scope")) or "all",
        "valid_from": _clean(row.get("valid_from")),
        "valid_to": _clean(row.get("valid_to")),
        "substitution_allowed": _clean(row.get("substitution_allowed")).lower() in ("true", "1", "yes"),
        "optional": list_type == "optional",
    }, []


def _normalize_price_row(row: dict, row_num: int = 0) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    prefix = f"Row {row_num}: " if row_num else ""
    sku = _clean(row.get("sku"))
    if not sku:
        errors.append(f"{prefix}sku is required")
    try:
        price = float(row.get("expected_price"))
        if price < 0:
            errors.append(f"{prefix}expected_price must be >= 0")
    except (TypeError, ValueError):
        errors.append(f"{prefix}expected_price must be a number")
        price = 0
    if errors:
        return None, errors
    return {
        "sku": sku,
        "label_location": _clean(row.get("label_location")) or "shelf_tag",
        "expected_price": round(price, 2),
        "currency": _clean(row.get("currency")) or "INR",
        "price_basis": _clean(row.get("price_basis")) or "item",
        "valid_from": _clean(row.get("valid_from")),
        "valid_to": _clean(row.get("valid_to")),
    }, []


def _normalize_promotion_row(row: dict, row_num: int = 0) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    prefix = f"Row {row_num}: " if row_num else ""
    promo_id = _clean(row.get("promotion_id"))
    skus_raw = _clean(row.get("participating_skus"))
    if not promo_id:
        errors.append(f"{prefix}promotion_id is required")
    if not skus_raw:
        errors.append(f"{prefix}participating_skus is required")
    facings_raw = row.get("required_facings")
    required_facings = None
    if facings_raw not in (None, ""):
        try:
            required_facings = max(0, int(facings_raw))
        except (TypeError, ValueError):
            errors.append(f"{prefix}required_facings must be a number")
    promo_price = None
    if row.get("expected_promo_price") not in (None, ""):
        try:
            promo_price = round(float(row.get("expected_promo_price")), 2)
        except (TypeError, ValueError):
            errors.append(f"{prefix}expected_promo_price must be a number")
    if errors:
        return None, errors
    return {
        "promotion_id": promo_id,
        "participating_skus": [s.strip() for s in skus_raw.split("|") if s.strip()],
        "start_date": _clean(row.get("start_date")),
        "end_date": _clean(row.get("end_date")),
        "required_location": _clean(row.get("required_location")),
        "expected_offer_text": _clean(row.get("expected_offer_text")),
        "expected_promo_price": promo_price,
        "required_facings": required_facings,
    }, []


def readiness_from_package(package: dict | None, product_rows: list[dict] | None) -> list[dict]:
    """Which KPIs can be calculated from supplied package fields."""
    package = package or {}
    products = product_rows or []
    has_prices = any(p.get("mrp_inr") not in (None, "") for p in products) or bool(package.get("price_requirements"))
    return [
        {"kpi_id": "osa", "ready": bool(products), "label": "Listed SKUs"},
        {"kpi_id": "planogram_compliance", "ready": bool(products), "label": "Shelf layout"},
        {"kpi_id": "assortment_compliance", "ready": bool(package.get("assortment_skus")), "label": "Assortment list"},
        {"kpi_id": "msl_compliance", "ready": bool(package.get("msl_skus")), "label": "Must-stock list"},
        {"kpi_id": "price_compliance", "ready": has_prices, "label": "Price requirements"},
        {"kpi_id": "promotional_compliance", "ready": bool(package.get("promotions")), "label": "Promotions"},
        {"kpi_id": "location_accuracy", "ready": any(str(p.get("shelf_position") or "").strip() for p in products), "label": "Slot IDs"},
        {"kpi_id": "facing_count", "ready": any(p.get("expected_facings") not in (None, "") for p in products), "label": "Expected facings"},
        {"kpi_id": "share_of_shelf", "ready": bool(package.get("primary_brand")), "label": "Brand scope"},
    ]
