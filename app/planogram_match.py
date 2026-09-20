"""Join planogram expected state with Astra CV actual state."""

from __future__ import annotations

import re
from typing import Any

from app.inventory import _normalize_brand_key
from app.planogram_csv import build_match_key

_MATCH_THRESHOLD = 0.72
_BRAND_MATCH_THRESHOLD = 0.55
_PLACEHOLDER_TOKENS = frozenset(
    {
        "unverifiable",
        "unknown",
        "unidentified",
        "n/a",
        "na",
        "none",
        "null",
        "-",
        "—",
    }
)


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _clean_identity_text(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        for token in _norm(part).split():
            if token in _PLACEHOLDER_TOKENS:
                continue
            tokens.append(token)
    return " ".join(tokens)


def _status_upper(row: dict[str, Any], key: str, default: str = "IDENTIFIED") -> str:
    return str(row.get(key) or default).strip().upper()


def _is_placeholder_field(value: Any) -> bool:
    text = _norm(value)
    return not text or text in _PLACEHOLDER_TOKENS


def _cv_product_unverified(cv: dict[str, Any]) -> bool:
    product_status = _status_upper(cv, "product_status")
    if product_status in {"UNVERIFIABLE", "UNKNOWN", "UNIDENTIFIED"}:
        return True
    return _is_placeholder_field(cv.get("product_name") or cv.get("product"))


def _cv_brand_identified(cv: dict[str, Any]) -> bool:
    if _is_placeholder_field(cv.get("brand")):
        return False
    return _status_upper(cv, "brand_status") in {"IDENTIFIED", "MATCHED", "OK", ""}


def _brand_keys_equal(a: Any, b: Any) -> bool:
    left = _normalize_brand_key(str(a or ""), "")
    right = _normalize_brand_key(str(b or ""), "")
    if not left or not right:
        return False
    if left == right:
        return True
    return left in right or right in left


def _cv_identity(row: dict[str, Any]) -> str:
    return build_match_key(
        str(row.get("brand") or ""),
        str(row.get("product_name") or row.get("product") or ""),
        sku=str(row.get("sku") or ""),
        variant=str(row.get("variant") or ""),
    )


def _planogram_identity(item: dict[str, Any]) -> str:
    return build_match_key(
        str(item.get("brand") or ""),
        str(item.get("product_name") or ""),
        sku=str(item.get("sku") or ""),
        variant=str(item.get("variant") or ""),
    )


def _token_overlap(a: str, b: str) -> float:
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _score_cv_to_planogram(cv: dict[str, Any], item: dict[str, Any]) -> float:
    cv_sku = _norm(cv.get("sku"))
    item_sku = _norm(item.get("sku"))
    if cv_sku and item_sku and cv_sku == item_sku and cv_sku not in _PLACEHOLDER_TOKENS:
        return 1.0
    if _cv_identity(cv) == _planogram_identity(item):
        return 0.95

    cv_text = _clean_identity_text(cv.get("brand"), cv.get("product_name") or cv.get("product"), cv.get("variant"))
    item_text = _clean_identity_text(item.get("brand"), item.get("product_name"), item.get("variant"))
    overlap = _token_overlap(cv_text, item_text) if cv_text and item_text else 0.0

    if _cv_brand_identified(cv) and _brand_keys_equal(cv.get("brand"), item.get("brand")):
        # Brand-only Astra rows (product UNVERIFIABLE) must still clear a brand gate
        # so presence/facings are not wiped when the SKU text is illegible.
        brand_score = 0.62 if _cv_product_unverified(cv) else 0.58
        exp_sub = _norm(item.get("sub_category") or item.get("subcategory") or "")
        cv_blob = _clean_identity_text(
            cv.get("product_name") or cv.get("product"),
            cv.get("variant"),
            cv.get("subcategory") or cv.get("sub_category"),
            cv.get("category"),
            cv.get("visual_notes"),
        )
        if exp_sub and exp_sub in cv_blob:
            brand_score = max(brand_score, 0.68)
        return max(overlap, brand_score)

    return overlap


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _match_status_for_score(cv: dict[str, Any], score: float) -> str:
    if score >= _MATCH_THRESHOLD and not _cv_product_unverified(cv):
        return "MATCHED"
    if score >= _BRAND_MATCH_THRESHOLD and _cv_brand_identified(cv):
        return "BRAND_MATCHED"
    if score >= 0.3:
        return "UNVERIFIABLE"
    return "NOT_FOUND"


def join_planogram_with_cv(
    planogram_items: list[dict[str, Any]],
    cv_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build per-planogram-row joined records for shelf_calc."""
    used_cv: set[int] = set()
    rows: list[dict[str, Any]] = []

    for item in planogram_items:
        best_idx = -1
        best_score = 0.0
        for idx, cv in enumerate(cv_products):
            if idx in used_cv:
                continue
            score = _score_cv_to_planogram(cv, item)
            if score > best_score:
                best_score = score
                best_idx = idx

        expected_facings = _int_or_none(item.get("expected_facings") or item.get("expected_qty"))
        expected_units = _int_or_none(item.get("expected_shelf_units"))
        base = {
            "location": item.get("location"),
            "category": item.get("category"),
            "subcategory": item.get("sub_category") or item.get("subcategory"),
            "brand": item.get("brand"),
            "product_name": item.get("product_name"),
            "variant": item.get("variant"),
            "sku": item.get("sku"),
            "expected_facings": expected_facings,
            "min_facings": _int_or_none(item.get("min_facings")),
            "max_facings": _int_or_none(item.get("max_facings")),
            "expected_shelf_units": expected_units,
            "expected_mrp_inr": _float_or_none(item.get("mrp_inr")),
            "avg_daily_sales": _float_or_none(item.get("avg_daily_sales")),
            "expected_shelf_position": item.get("shelf_position"),
            "actual_shelf_position": None,
            "source_expected": "planogram",
        }

        if best_idx < 0:
            rows.append(
                {
                    **base,
                    "actual_facings": None,
                    "actual_visible_units": None,
                    "match_status": "NOT_FOUND",
                    "match_score": round(best_score, 3),
                    "source_actual": None,
                }
            )
            continue

        candidate = cv_products[best_idx]
        if _cv_product_unverified(candidate) and _cv_brand_identified(candidate):
            accept_threshold = _BRAND_MATCH_THRESHOLD
        else:
            accept_threshold = _MATCH_THRESHOLD

        if best_score < accept_threshold:
            rows.append(
                {
                    **base,
                    "actual_facings": None,
                    "actual_visible_units": None,
                    "match_status": "NOT_FOUND" if best_score < 0.3 else "UNVERIFIABLE",
                    "match_score": round(best_score, 3),
                    "source_actual": None,
                }
            )
            continue

        cv = cv_products[best_idx]
        used_cv.add(best_idx)
        match_status = _match_status_for_score(cv, best_score)
        # Brand-level accept still transfers visible facings so Aislix does not
        # invent zero-unit CRITICAL risks when the brand is clearly on shelf.
        rows.append(
            {
                **base,
                "actual_facings": _int_or_none(cv.get("actual_facings")),
                "actual_visible_units": _int_or_none(cv.get("actual_visible_units")),
                "actual_shelf_position": cv.get("shelf_position") or cv.get("actual_shelf_position"),
                "match_status": match_status,
                "match_score": round(best_score, 3),
                "confidence": cv.get("confidence"),
                "source_actual": "astra",
                "brand_status": cv.get("brand_status"),
                "product_status": cv.get("product_status"),
                "variant_status": cv.get("variant_status"),
            }
        )

    return rows
