"""Parse and validate planogram CSV / manual row input."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from app.scan_context import normalize_planogram_category, normalize_sub_category_id

REQUIRED_FIELDS = ("location", "category", "sub_category", "brand", "product_name")

HEADER_ALIASES: dict[str, str] = {
    "location": "location",
    "store": "location",
    "aisle": "aisle",
    "category": "category",
    "sub-category": "sub_category",
    "subcategory": "sub_category",
    "sub category": "sub_category",
    "brand": "brand",
    "product": "product_name",
    "product name": "product_name",
    "variant": "variant",
    "size": "variant",
    "pack size": "variant",
    "expected facings": "expected_facings",
    "expected_facings": "expected_facings",
    "facings": "expected_facings",
    "target facings": "expected_facings",
    "min facings": "min_facings",
    "min_facings": "min_facings",
    "max facings": "max_facings",
    "max_facings": "max_facings",
    "expected shelf units": "expected_shelf_units",
    "expected_shelf_units": "expected_shelf_units",
    "shelf units": "expected_shelf_units",
    "expected qty": "expected_qty",
    "expected quantity": "expected_qty",
    "qty": "expected_qty",
    "quantity": "expected_qty",
    "sku": "sku",
    "product id": "sku",
    "product_id": "sku",
    "productid": "sku",
    "shelf position": "shelf_position",
    "position": "shelf_position",
    "mrp": "mrp_inr",
    "mrp inr": "mrp_inr",
    "mrp_inr": "mrp_inr",
    "price": "mrp_inr",
    "price inr": "mrp_inr",
    "daily sales": "avg_daily_sales",
    "avg daily sales": "avg_daily_sales",
    "sales": "avg_daily_sales",
    "velocity": "avg_daily_sales",
    "units per day": "avg_daily_sales",
}


def csv_template_header() -> str:
    """Canonical planogram CSV header for downloads and docs."""
    return (
        "location,category,sub_category,brand,product_name,variant,"
        "expected_facings,min_facings,max_facings,expected_shelf_units,"
        "price,avg_daily_sales,product_id,shelf_position"
    )


def _normalize_header(header: str) -> str:
    key = re.sub(r"\s+", " ", header.strip().lower())
    return HEADER_ALIASES.get(key, key.replace(" ", "_"))


def build_match_key(
    brand: str,
    product_name: str,
    sku: str = "",
    sub_category: str = "",
    variant: str = "",
) -> str:
    parts = [
        brand.lower().strip(),
        product_name.lower().strip(),
        variant.lower().strip(),
        sku.lower().strip(),
        sub_category.lower().strip(),
    ]
    return "|".join(p for p in parts if p)


def normalize_planogram_row(row: dict[str, Any], row_num: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    prefix = f"Row {row_num}: " if row_num else ""

    brand = str(row.get("brand") or "").strip()
    product_name = str(row.get("product_name") or row.get("product") or "").strip()
    category = normalize_planogram_category(str(row.get("category") or "").strip())
    location = str(row.get("location") or "").strip()
    sub_category = str(row.get("sub_category") or "").strip()

    if not location:
        errors.append(f"{prefix}location is required")
    if not brand:
        errors.append(f"{prefix}brand is required")
    if not product_name:
        errors.append(f"{prefix}product_name is required")
    if not category:
        errors.append(f"{prefix}category is required")
    if not sub_category:
        errors.append(f"{prefix}sub_category is required")

    def _parse_int_field(name: str, raw: Any, *, required: bool = False) -> int | None:
        if raw in (None, ""):
            if required:
                errors.append(f"{prefix}{name} is required")
            return None
        try:
            val = int(raw)
            if val < 0:
                errors.append(f"{prefix}{name} must be >= 0")
            return val
        except (TypeError, ValueError):
            errors.append(f"{prefix}{name} must be a number")
            return None

    expected_facings = _parse_int_field("expected_facings", row.get("expected_facings"))
    min_facings = _parse_int_field("min_facings", row.get("min_facings"))
    max_facings = _parse_int_field("max_facings", row.get("max_facings"))
    expected_shelf_units = _parse_int_field("expected_shelf_units", row.get("expected_shelf_units"))
    expected_qty = _parse_int_field("expected_qty", row.get("expected_qty", row.get("quantity")))

    if expected_facings is None and expected_qty is None:
        errors.append(f"{prefix}expected_facings or expected_qty is required")

    if min_facings is not None and max_facings is not None and min_facings > max_facings:
        errors.append(f"{prefix}min_facings cannot exceed max_facings")

    if errors:
        return None, errors

    sub_category = normalize_sub_category_id(sub_category, category)
    variant = str(row.get("variant") or "").strip()
    sku = str(row.get("sku") or row.get("product_id") or row.get("product id") or "").strip()

    mrp_inr: float | None = None
    mrp_raw = row.get("mrp_inr", row.get("mrp", row.get("price")))
    if mrp_raw not in (None, ""):
        try:
            mrp_inr = float(mrp_raw)
            if mrp_inr < 0:
                errors.append(f"{prefix}price must be >= 0")
        except (TypeError, ValueError):
            errors.append(f"{prefix}price must be a number")

    avg_daily_sales: float | None = None
    sales_raw = row.get("avg_daily_sales", row.get("sales"))
    if sales_raw not in (None, ""):
        try:
            avg_daily_sales = float(sales_raw)
            if avg_daily_sales < 0:
                errors.append(f"{prefix}avg_daily_sales must be >= 0")
        except (TypeError, ValueError):
            errors.append(f"{prefix}avg_daily_sales must be a number")

    if errors:
        return None, errors

    normalized = {
        "location": location,
        "aisle": str(row.get("aisle") or "").strip(),
        "category": category,
        "sub_category": sub_category,
        "brand": brand,
        "product_name": product_name,
        "variant": variant,
        "sku": sku,
        "expected_qty": expected_qty if expected_qty is not None else (expected_facings or 0),
        "shelf_position": str(row.get("shelf_position") or "").strip(),
        "match_key": build_match_key(brand, product_name, sku, sub_category, variant),
    }
    if expected_facings is not None:
        normalized["expected_facings"] = expected_facings
    if min_facings is not None:
        normalized["min_facings"] = min_facings
    if max_facings is not None:
        normalized["max_facings"] = max_facings
    if expected_shelf_units is not None:
        normalized["expected_shelf_units"] = expected_shelf_units
    if mrp_inr is not None:
        normalized["mrp_inr"] = round(mrp_inr, 2)
    if avg_daily_sales is not None:
        normalized["avg_daily_sales"] = round(avg_daily_sales, 2)
    return normalized, []


def parse_csv_text(content: str, delimiter: str | None = None) -> dict[str, Any]:
    if not content or not content.strip():
        return {"rows": [], "errors": ["CSV is empty"], "valid_count": 0, "error_count": 0}

    content = content.lstrip("\ufeff")
    sample = content[:4096]
    if delimiter is None:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        return {"rows": [], "errors": ["Missing header row"], "valid_count": 0, "error_count": 0}

    field_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    header_errors: list[str] = []
    required_headers = {
        "location": "location",
        "category": "category",
        "sub_category": "sub_category",
        "brand": "brand",
        "product_name": "product / product_name",
    }
    for canon, label in required_headers.items():
        if canon not in field_map and not (canon == "product_name" and "product" in field_map):
            header_errors.append(f"Missing required column: {label}")
    if not any(k in field_map for k in ("expected_facings", "expected_qty", "qty", "quantity", "facings")):
        header_errors.append("Missing required column: expected_facings or expected_qty")
    if header_errors:
        return {"rows": [], "errors": header_errors, "valid_count": 0, "error_count": len(header_errors)}

    rows: list[dict] = []
    all_errors: list[str] = []
    valid_count = 0

    for idx, raw in enumerate(reader, start=2):
        mapped: dict[str, Any] = {}
        for canon, original in field_map.items():
            mapped[canon] = raw.get(original, "")
        normalized, row_errors = normalize_planogram_row(mapped, row_num=idx)
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
