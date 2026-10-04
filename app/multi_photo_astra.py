"""
Multi-photo AI Audits: Astra reads each shelf photo on its own (prompt unchanged), then the
per-photo shelf_cv JSON is merged into one payload before Aislix matching and calc.

Photos are expected to show different sections of the shelf (the UI asks for no overlap),
so product rows are kept per photo and totals are summed.
"""

from __future__ import annotations

import copy
from typing import Any

_QUALITY_RANK = {"GOOD": 0, "LIMITED": 1, "POOR": 2}
_SUMMED_LISTS = ("location_labels", "visible_prices", "visible_promotions", "shelf_issues")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_mergeable_shelf_cv(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("products"), list)


def merge_astra_photo_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-photo Astra shelf_cv JSON into one payload. One payload is returned unchanged."""
    if len(payloads) <= 1:
        return payloads[0] if payloads else {}
    if not all(is_mergeable_shelf_cv(p) for p in payloads):
        return payloads[0]

    merged = copy.deepcopy(payloads[0])
    products: list[dict[str, Any]] = []
    facings_per_photo: list[int] = []
    for index, payload in enumerate(payloads, start=1):
        photo_facings = 0
        for row in payload.get("products") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["photo_index"] = index
            products.append(item)
            photo_facings += max(0, _int(item.get("actual_facings")) or 0)
        facings_per_photo.append(photo_facings)
    merged["products"] = products

    for key in _SUMMED_LISTS:
        rows: list[Any] = []
        seen_labels: set[str] = set()
        for index, payload in enumerate(payloads, start=1):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if key == "location_labels" and isinstance(value, dict):
                    label = _norm(value.get("label"))
                    if label and label in seen_labels:
                        continue
                    if label:
                        seen_labels.add(label)
                rows.append({**value, "photo_index": index} if isinstance(value, dict) else value)
        if rows:
            merged[key] = rows

    qualities = [str(p.get("image_quality") or "").upper() for p in payloads]
    ranked = [q for q in qualities if q in _QUALITY_RANK]
    if ranked:
        merged["image_quality"] = max(ranked, key=lambda q: _QUALITY_RANK[q])

    summary = dict(merged.get("summary") or {}) if isinstance(merged.get("summary"), dict) else {}
    for key in ("total_actual_facings", "total_actual_visible_units", "prices_read"):
        values = [
            _int((p.get("summary") or {}).get(key)) if isinstance(p.get("summary"), dict) else None
            for p in payloads
        ]
        if all(v is not None for v in values):
            summary[key] = sum(v for v in values if v is not None)
        else:
            summary.pop(key, None)

    def _unique(*fields: str) -> int:
        keys = set()
        for row in products:
            key = "|".join(_norm(row.get(f)) for f in fields)
            if key.strip("|"):
                keys.add(key)
        return len(keys)

    summary["products_detected"] = _unique("brand", "product", "variant")
    summary["brands_detected"] = _unique("brand")
    summary["categories_detected"] = _unique("category")
    if isinstance(merged.get("location_labels"), list):
        summary["location_labels_read"] = len(merged["location_labels"])
    merged["summary"] = summary
    merged["multi_photo"] = {
        "photo_count": len(payloads),
        "facings_per_photo": facings_per_photo,
        "merged_facings": sum(facings_per_photo),
    }
    return merged
