"""Shelf-edge location labels, rack markers and visible prices read by Astra."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = frozenset({"", "null", "none", "n/a", "na", "-", "—", "unverifiable", "not visible"})


def normalize_label(value: Any) -> str:
    """Canonical label text: upper-case, no surrounding/inner whitespace around hyphens."""
    text = str(value or "").strip().upper()
    if text.lower() in _PLACEHOLDER:
        return ""
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", "", text)


def _label_status(row: dict[str, Any], label: str) -> str:
    status = str(row.get("location_label_status") or row.get("status") or "").strip().upper()
    if not label:
        return "NOT_VISIBLE"
    if "?" in label:
        return "PARTIAL"
    return status if status in {"READ", "PARTIAL"} else "READ"


def labels_match(actual: Any, expected: Any) -> bool:
    """True when a read label equals the expected label; '?' in the read label matches any character."""
    a = normalize_label(actual)
    e = normalize_label(expected)
    if not a or not e or len(a) != len(e):
        return False
    return all(ca == "?" or ca == ce for ca, ce in zip(a, e))


def _labels_compatible(a: str, b: str) -> bool:
    """Two read labels could be the same physical label ('?' is unknown on either side)."""
    return len(a) == len(b) and all(ca == cb or "?" in (ca, cb) for ca, cb in zip(a, b))


def _ambiguous_labels(labels: list[str]) -> set[str]:
    """Partial labels that could be two or more other labels read in the photo, e.g. 'AMB-D07??'."""
    return {
        label
        for label in labels
        if "?" in label and sum(1 for other in labels if other != label and _labels_compatible(label, other)) >= 2
    }


def _rack(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text or text.lower() in _PLACEHOLDER:
        return None
    return text


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def visible_price_value(value: Any) -> float | None:
    """Parse an Astra visible price ("199", "₹ 199.00", 199) into a number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    try:
        price = float(match.group(0))
    except ValueError:
        return None
    return price if price > 0 else None


def _product_identity(row: dict[str, Any]) -> str:
    parts = [row.get("brand"), row.get("product_name") or row.get("product"), row.get("variant")]
    return "|".join(re.sub(r"\s+", " ", str(p or "").strip().lower()) for p in parts)


def build_location_analysis(
    products: list[dict[str, Any]],
    astra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Roll products up by shelf-edge label; list empty labelled sections, racks and prices read."""
    labels: dict[str, dict[str, Any]] = {}
    racks: set[str] = set()
    has_location_field = False
    has_price_field = False
    prices_read = 0
    without_location = 0

    for row in products:
        if not isinstance(row, dict):
            continue
        if "location_label" in row:
            has_location_field = True
        if "visible_price" in row:
            has_price_field = True
            if visible_price_value(row.get("visible_price")) is not None:
                prices_read += 1
        rack = _rack(row.get("rack_marker"))
        if rack:
            racks.add(rack)
        label = normalize_label(row.get("location_label"))
        if not label:
            without_location += 1
            continue
        entry = labels.setdefault(
            label,
            {
                "label": label,
                "rack_marker": rack,
                "label_status": _label_status(row, label),
                "_products": set(),
                "_rows": 0,
                "facings": 0,
                "visible_units": 0,
            },
        )
        entry["_products"].add(_product_identity(row))
        entry["_rows"] += 1
        entry["facings"] += _int(row.get("actual_facings"))
        entry["visible_units"] += _int(row.get("actual_visible_units"))
        if not entry["rack_marker"] and rack:
            entry["rack_marker"] = rack

    for raw in (astra_payload or {}).get("location_labels") or []:
        if not isinstance(raw, dict):
            continue
        has_location_field = True
        label = normalize_label(raw.get("label"))
        if not label:
            continue
        rack = _rack(raw.get("rack_marker"))
        if rack:
            racks.add(rack)
        entry = labels.setdefault(
            label,
            {
                "label": label,
                "rack_marker": rack,
                "label_status": _label_status(raw, label),
                "_products": set(),
                "_rows": 0,
                "facings": 0,
                "visible_units": 0,
            },
        )
        if not entry["rack_marker"] and rack:
            entry["rack_marker"] = rack

    ambiguous = _ambiguous_labels(list(labels))
    ambiguous_rows = 0
    for label in ambiguous:
        ambiguous_rows += labels.pop(label)["_rows"]

    locations: list[dict[str, Any]] = []
    for label in sorted(labels):
        entry = labels[label]
        entry.pop("_rows")
        product_count = len(entry.pop("_products"))
        entry["products"] = product_count
        entry["empty"] = product_count == 0
        locations.append(entry)
    empty = [row for row in locations if row["empty"]]

    return {
        "available": has_location_field,
        "locations": locations,
        "empty_locations": empty,
        "metrics": {
            "location_labels_read": len(locations) if has_location_field else None,
            "empty_locations": len(empty) if has_location_field else None,
            "racks_detected": len(racks) if has_location_field else None,
            "products_without_location": without_location + ambiguous_rows if has_location_field else None,
            "ambiguous_labels": len(ambiguous) if has_location_field else None,
            "prices_read": prices_read if has_price_field else None,
        },
        "ambiguous_label_values": sorted(ambiguous),
    }


def labels_in_photo(location_analysis: dict[str, Any]) -> list[str]:
    return [row["label"] for row in location_analysis.get("locations") or [] if row.get("label")]


def location_status(
    expected: Any,
    actual_label: Any,
    photo_labels: list[str],
    ambiguous_labels: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """
    CORRECT / WRONG_LOCATION / NOT_READABLE / EXPECTED_NOT_IN_PHOTO / NO_EXPECTED.

    WRONG_LOCATION is only possible when the expected label itself was read in this photo,
    so store-level locations (e.g. "A-1-L") never produce false wrong-location flags.
    """
    exp = normalize_label(expected)
    if not exp:
        return "NO_EXPECTED"
    act = normalize_label(actual_label)
    if act in ambiguous_labels:
        act = ""
    if act and labels_match(act, exp):
        return "CORRECT"
    expected_visible = any(labels_match(label, exp) for label in photo_labels)
    if not expected_visible:
        return "EXPECTED_NOT_IN_PHOTO"
    if not act:
        return "NOT_READABLE"
    if "?" in act:
        return "NOT_READABLE"
    return "WRONG_LOCATION"


def price_status(expected_price: Any, visible_price: Any) -> str:
    """MATCH / MISMATCH / NOT_READABLE / NO_EXPECTED (exact to the paisa after rounding)."""
    expected = visible_price_value(expected_price)
    if expected is None:
        return "NO_EXPECTED"
    actual = visible_price_value(visible_price)
    if actual is None:
        return "NOT_READABLE"
    return "MATCH" if round(actual, 2) == round(expected, 2) else "MISMATCH"


def annotate_planogram_rows(rows: list[dict[str, Any]], location_analysis: dict[str, Any]) -> None:
    """Add location_status / price_status to joined planogram rows in place."""
    photo_labels = labels_in_photo(location_analysis)
    ambiguous = set(location_analysis.get("ambiguous_label_values") or [])
    for row in rows:
        if row.get("source_actual") is None:
            continue
        if location_analysis.get("available"):
            row["location_status"] = location_status(
                row.get("expected_location") or row.get("location"),
                row.get("actual_location_label"),
                photo_labels,
                ambiguous,
            )
        if "visible_price" in row:
            row["price_status"] = price_status(row.get("expected_mrp_inr"), row.get("visible_price"))
            actual = visible_price_value(row.get("visible_price"))
            expected = visible_price_value(row.get("expected_mrp_inr"))
            row["price_difference"] = (
                round(actual - expected, 2) if actual is not None and expected is not None else None
            )
