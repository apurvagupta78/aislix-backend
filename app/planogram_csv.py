"""Parse and validate planogram CSV / manual row input."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

REQUIRED_FIELDS = ("category", "brand", "product_name", "expected_qty")

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
    "expected qty": "expected_qty",
    "expected quantity": "expected_qty",
    "qty": "expected_qty",
    "quantity": "expected_qty",
    "sku": "sku",
    "shelf position": "shelf_position",
    "position": "shelf_position",
}


def _normalize_header(header: str) -> str:
    key = re.sub(r"\s+", " ", header.strip().lower())
    return HEADER_ALIASES.get(key, key.replace(" ", "_"))


def build_match_key(brand: str, product_name: str, sku: str = "", sub_category: str = "") -> str:
    parts = [
        brand.lower().strip(),
        product_name.lower().strip(),
        sku.lower().strip(),
        sub_category.lower().strip(),
    ]
    return "|".join(p for p in parts if p)


def normalize_planogram_row(row: dict[str, Any], row_num: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    prefix = f"Row {row_num}: " if row_num else ""

    brand = str(row.get("brand") or "").strip()
    product_name = str(row.get("product_name") or row.get("product") or "").strip()
    category = str(row.get("category") or "").strip()

    if not brand:
        errors.append(f"{prefix}brand is required")
    if not product_name:
        errors.append(f"{prefix}product_name is required")
    if not category:
        errors.append(f"{prefix}category is required")

    qty_raw = row.get("expected_qty", row.get("quantity", 1))
    try:
        expected_qty = int(qty_raw)
        if expected_qty < 0:
            errors.append(f"{prefix}expected_qty must be >= 0")
    except (TypeError, ValueError):
        errors.append(f"{prefix}expected_qty must be a number")
        expected_qty = 0

    if errors:
        return None, errors

    sub_category = str(row.get("sub_category") or "").strip()
    sku = str(row.get("sku") or "").strip()
    normalized = {
        "location": str(row.get("location") or "").strip(),
        "aisle": str(row.get("aisle") or "").strip(),
        "category": category,
        "sub_category": sub_category,
        "brand": brand,
        "product_name": product_name,
        "sku": sku,
        "expected_qty": expected_qty,
        "shelf_position": str(row.get("shelf_position") or "").strip(),
        "match_key": build_match_key(brand, product_name, sku, sub_category),
    }
    return normalized, []


def parse_csv_text(content: str, delimiter: str | None = None) -> dict[str, Any]:
    if not content or not content.strip():
        return {"rows": [], "errors": ["CSV is empty"], "valid_count": 0, "error_count": 0}

    sample = content[:4096]
    if delimiter is None:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        return {"rows": [], "errors": ["Missing header row"], "valid_count": 0, "error_count": 0}

    field_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    header_errors: list[str] = []
    if "brand" not in field_map:
        header_errors.append("Missing required column: brand")
    if "product_name" not in field_map:
        header_errors.append("Missing required column: product / product_name")
    if "category" not in field_map:
        header_errors.append("Missing required column: category")
    if header_errors:
        return {"rows": [], "errors": header_errors, "valid_count": 0, "error_count": len(header_errors)}

    rows: list[dict] = []
    all_errors: list[str] = []
    valid_count = 0

    for idx, raw in enumerate(reader, start=2):
        mapped: dict[str, Any] = {}
        for canon, original in field_map.items():
            mapped[canon] = raw.get(original, "")
        if "expected_qty" not in mapped or str(mapped.get("expected_qty", "")).strip() == "":
            mapped["expected_qty"] = 1

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
