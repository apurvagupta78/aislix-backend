"""Compare a customer reference document (invoice, pick list, CSV) with what Astra saw on the shelf."""

from __future__ import annotations

from typing import Any

from app.location_analysis import annotate_planogram_rows, normalize_label
from app.planogram_match import _brand_keys_equal, join_planogram_with_cv

MATCHES_PRESENCE_PERCENT = 90.0
PARTIAL_PRESENCE_PERCENT = 60.0

_FOUND = {"MATCHED"}
_FOUND_BRAND_ONLY = {"BRAND_MATCHED"}


def is_reference_comparison(metadata: dict[str, Any]) -> bool:
    basis = str(metadata.get("comparison_basis") or "").strip().lower()
    items = metadata.get("reference_items")
    return basis == "reference" and isinstance(items, list) and any(isinstance(i, dict) for i in items)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


_NO_PROMO = {"null", "none", "n/a", "na", "-", "no", "no offer", "no promotion"}
_PROMO_KEY = ("promo", "offer", "scheme", "deal")


def _promo_text(value: Any) -> str | None:
    text = _text(value)
    return None if text is None or text.lower() in _NO_PROMO else text


def _expected_promo(item: dict[str, Any]) -> str | None:
    """The document's promotion for a line: `expected_promo`, else a Promo / Offer / Scheme column."""
    direct = _promo_text(item.get("expected_promo"))
    if direct:
        return direct
    extra = item.get("extra_fields")
    if isinstance(extra, dict):
        for key, value in extra.items():
            if any(word in str(key).lower() for word in _PROMO_KEY):
                found = _promo_text(value)
                if found:
                    return found
    return None


def _promo_status(expected: str | None, shelf: str | None, *, found: bool) -> str:
    if not found:
        return "NOT_ON_SHELF"
    if expected:
        return "PROMO_SEEN" if shelf else "PROMO_NOT_SEEN"
    return "UNEXPECTED_PROMO" if shelf else "NO_EXPECTED"


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100.0 / whole, 1) if whole else None


def _join_item(item: dict[str, Any]) -> dict[str, Any]:
    """Shape one document line for the planogram matcher (presence target, expected bin and price)."""
    expected_location = _text(item.get("expected_location")) or _text(item.get("location"))
    return {
        "brand": item.get("brand"),
        "product_name": item.get("product_name") or item.get("product"),
        "variant": item.get("variant"),
        "sku": item.get("sku"),
        "category": item.get("category"),
        "sub_category": item.get("sub_category"),
        "location": expected_location,
        "expected_location": expected_location,
        "expected_qty": 1,
        "expected_price": _num(item.get("expected_price")),
    }


def _presence_status(row: dict[str, Any], item: dict[str, Any], unplanned: list[dict[str, Any]]) -> str:
    """UNCLEAR only when the line's brand is still on the shelf unmatched; otherwise the line is missing."""
    status = str(row.get("match_status") or "").upper()
    if row.get("source_actual") is not None and status in _FOUND:
        return "FOUND"
    if row.get("source_actual") is not None and status in _FOUND_BRAND_ONLY:
        return "FOUND_VARIANT_UNVERIFIED"
    if status == "UNVERIFIABLE" and any(_brand_keys_equal(item.get("brand"), cv.get("brand")) for cv in unplanned):
        return "UNCLEAR"
    return "MISSING"


def _qty_status(invoice_qty: float | None, shelf_units: int | None, *, count_pending: bool, found: bool) -> str:
    if not found:
        return "NOT_ON_SHELF"
    if count_pending:
        return "PENDING"
    if invoice_qty is None or shelf_units is None:
        return "NO_EXPECTED" if invoice_qty is None else "NOT_COUNTED"
    return "COVERED" if shelf_units >= invoice_qty else "BELOW_DOCUMENT"


def _line(
    item: dict[str, Any],
    row: dict[str, Any],
    index: int,
    unplanned: list[dict[str, Any]],
    *,
    count_pending: bool,
) -> dict[str, Any]:
    presence = _presence_status(row, item, unplanned)
    found = presence in {"FOUND", "FOUND_VARIANT_UNVERIFIED"}
    invoice_qty = _num(item.get("invoice_qty"))
    shelf_units = row.get("actual_visible_units") if found else None
    shelf_facings = row.get("actual_facings") if found else None
    expected_location = normalize_label(item.get("expected_location") or item.get("location")) or None
    if not expected_location:
        location = "NO_EXPECTED"
    else:
        location = row.get("location_status") if found else None
    expected_promo = _expected_promo(item)
    shelf_promo = _promo_text(row.get("promotion_text")) if found else None
    return {
        "line_no": item.get("line_no") if item.get("line_no") is not None else index + 1,
        "raw_text": _text(item.get("raw_text")),
        "brand": _text(item.get("brand")),
        "product_name": _text(item.get("product_name") or item.get("product")),
        "variant": _text(item.get("variant")),
        "pack_size": _text(item.get("pack_size")),
        "invoice_qty": invoice_qty,
        "quantity_unit": _text(item.get("quantity_unit")),
        "expected_price": _num(item.get("expected_price")),
        "expected_location": expected_location,
        "document_confidence": item.get("confidence"),
        "presence_status": presence,
        "match_status": row.get("match_status"),
        "match_score": row.get("match_score"),
        "actual_brand": row.get("actual_brand") if found else None,
        "actual_product_name": row.get("actual_product_name") if found else None,
        "actual_variant": row.get("actual_variant") if found else None,
        "shelf_facings": None if count_pending else shelf_facings,
        "shelf_units": None if count_pending else shelf_units,
        "qty_status": _qty_status(invoice_qty, shelf_units, count_pending=count_pending, found=found),
        "shelf_location_label": row.get("actual_location_label") if found else None,
        "additional_location_labels": row.get("additional_location_labels") or [],
        "location_status": location,
        "visible_price": row.get("visible_price") if found else None,
        "price_status": row.get("price_status") if found else None,
        "price_difference": row.get("price_difference") if found else None,
        "expected_promo": expected_promo,
        "shelf_promotion": shelf_promo,
        "shelf_promotion_type": row.get("promotion_type") if shelf_promo else None,
        "shelf_promo_price": row.get("promo_price") if shelf_promo else None,
        "promo_status": _promo_status(expected_promo, shelf_promo, found=found),
    }


def _not_on_document(row: dict[str, Any], *, count_pending: bool) -> dict[str, Any]:
    return {
        "brand": _text(row.get("actual_brand") or row.get("brand")),
        "product_name": _text(row.get("actual_product_name") or row.get("product_name")),
        "variant": _text(row.get("actual_variant") or row.get("variant")),
        "shelf_facings": None if count_pending else row.get("actual_facings"),
        "shelf_units": None if count_pending else row.get("actual_visible_units"),
        "shelf_location_label": row.get("actual_location_label"),
        "visible_price": row.get("visible_price"),
        "shelf_promotion": _promo_text(row.get("promotion_text")),
        "shelf_promo_price": row.get("promo_price") if _promo_text(row.get("promotion_text")) else None,
        "confidence": row.get("confidence"),
        "brand_status": row.get("brand_status"),
        "product_status": row.get("product_status"),
    }


def _verdict(presence_percent: float | None, price_mismatched: int, location_wrong: int) -> str | None:
    if presence_percent is None:
        return None
    if presence_percent >= MATCHES_PRESENCE_PERCENT and not price_mismatched and not location_wrong:
        return "MATCHES"
    if presence_percent >= PARTIAL_PRESENCE_PERCENT:
        return "PARTIAL"
    return "DOES_NOT_MATCH"


def build_reference_match(
    reference_items: list[dict[str, Any]],
    cv_products: list[dict[str, Any]],
    location_analysis: dict[str, Any],
    *,
    count_pending: bool,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-line presence / quantity / price / location verdict for a reference document."""
    items = [item for item in reference_items if isinstance(item, dict)]
    rows, unplanned = join_planogram_with_cv([_join_item(item) for item in items], cv_products)
    annotate_planogram_rows(rows, location_analysis)

    lines = [
        _line(item, row, idx, unplanned, count_pending=count_pending)
        for idx, (item, row) in enumerate(zip(items, rows))
    ]
    extra = [_not_on_document(row, count_pending=count_pending) for row in unplanned]

    found = sum(1 for line in lines if line["presence_status"] in {"FOUND", "FOUND_VARIANT_UNVERIFIED"})
    unclear = sum(1 for line in lines if line["presence_status"] == "UNCLEAR")
    missing = sum(1 for line in lines if line["presence_status"] == "MISSING")
    price_checked = [line for line in lines if line["price_status"] in {"MATCH", "MISMATCH"}]
    price_matched = sum(1 for line in price_checked if line["price_status"] == "MATCH")
    price_mismatched = len(price_checked) - price_matched
    location_checked = [line for line in lines if line["location_status"] in {"CORRECT", "WRONG_LOCATION"}]
    location_correct = sum(1 for line in location_checked if line["location_status"] == "CORRECT")
    location_wrong = len(location_checked) - location_correct
    qty_checked = [line for line in lines if line["qty_status"] in {"COVERED", "BELOW_DOCUMENT"}]
    promo_expected = [line for line in lines if line["expected_promo"]]

    invoice_total = sum(line["invoice_qty"] for line in lines if line["invoice_qty"] is not None)
    shelf_total = (
        None
        if count_pending
        else sum(int(line["shelf_units"] or 0) for line in lines if line["shelf_units"] is not None)
    )
    presence_percent = _percent(found, len(lines))

    return {
        "available": True,
        "document": document or {},
        "count_pending": count_pending,
        "verdict": _verdict(presence_percent, price_mismatched, location_wrong),
        "thresholds": {
            "matches_presence_percent": MATCHES_PRESENCE_PERCENT,
            "partial_presence_percent": PARTIAL_PRESENCE_PERCENT,
        },
        "metrics": {
            "lines_total": len(lines),
            "lines_found": found,
            "lines_unclear": unclear,
            "lines_missing": missing,
            "presence_percent": presence_percent,
            "invoice_qty_total": invoice_total if any(line["invoice_qty"] is not None for line in lines) else None,
            "shelf_units_on_document_lines": shelf_total,
            "qty_lines_checked": len(qty_checked),
            "qty_lines_covered": sum(1 for line in qty_checked if line["qty_status"] == "COVERED"),
            "price_lines_checked": len(price_checked),
            "price_lines_matched": price_matched,
            "price_lines_mismatched": price_mismatched,
            "price_match_percent": _percent(price_matched, len(price_checked)),
            "prices_on_document": sum(1 for line in lines if line["expected_price"] is not None),
            "location_lines_checked": len(location_checked),
            "location_lines_correct": location_correct,
            "location_lines_wrong": location_wrong,
            "location_match_percent": _percent(location_correct, len(location_checked)),
            "locations_on_document": sum(1 for line in lines if line["expected_location"]),
            "promo_lines_expected": len(promo_expected),
            "promo_lines_seen": sum(1 for line in promo_expected if line["promo_status"] == "PROMO_SEEN"),
            "promo_lines_not_seen": sum(1 for line in promo_expected if line["promo_status"] == "PROMO_NOT_SEEN"),
            "shelf_promotions_read": sum(1 for line in lines if line["shelf_promotion"])
            + sum(1 for row in extra if row["shelf_promotion"]),
            "not_on_document": len(extra),
        },
        "lines": lines,
        "not_on_document": extra,
    }
