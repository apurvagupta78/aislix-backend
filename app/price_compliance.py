"""
Price tag compliance — compare detected shelf prices (OCR) to planogram / price master.
"""

from __future__ import annotations

import re
from typing import Any

_PRICE_RE = re.compile(
    r"(?:mrp|rs\.?|₹|inr|price)\s*[:\-]?\s*(\d{1,6}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_BARE_PRICE_RE = re.compile(r"\b(\d{2,5})\b")


def extract_price_inr(pack_text: str | None) -> float | None:
    text = (pack_text or "").strip()
    if not text:
        return None
    for pattern in (_PRICE_RE, _BARE_PRICE_RE):
        match = pattern.search(text.replace(",", ""))
        if match:
            try:
                value = float(match.group(1))
                if 5 <= value <= 50000:
                    return value
            except ValueError:
                continue
    return None


def compute_price_compliance(
    classified: list[dict],
    planogram_items: list[dict] | None,
    *,
    tolerance_inr: float = 5.0,
) -> dict[str, Any]:
    if not planogram_items:
        return {"state": "not_configured", "compliance_percent": None, "lines": []}

    plano_by_key: dict[str, dict] = {}
    for item in planogram_items:
        brand = str(item.get("brand") or "").strip().lower()
        product = str(item.get("product_name") or item.get("product") or "").strip().lower()
        key = str(item.get("match_key") or "").strip().lower() or f"{brand}|{product}"
        plano_by_key[key] = item

    lines: list[dict] = []
    checked = 0
    compliant = 0

    for row in classified:
        brand = str(row.get("brand") or "").strip().lower()
        product = str(row.get("product_name") or "").strip().lower()
        key = f"{brand}|{product}"
        plano = plano_by_key.get(key)
        if not plano:
            continue
        expected = plano.get("mrp_inr") or plano.get("price_inr")
        if expected in (None, ""):
            continue
        expected_f = float(expected)
        detected = row.get("detected_price_inr")
        if detected is None:
            detected = extract_price_inr(row.get("pack_text"))
        if detected is None:
            lines.append(
                {
                    "brand": row.get("brand"),
                    "product": row.get("product_name"),
                    "expected_price_inr": expected_f,
                    "detected_price_inr": None,
                    "variance_inr": None,
                    "status": "not_observable",
                }
            )
            continue
        checked += 1
        variance = round(float(detected) - expected_f, 2)
        ok = abs(variance) <= tolerance_inr
        if ok:
            compliant += 1
        lines.append(
            {
                "brand": row.get("brand"),
                "product": row.get("product_name"),
                "expected_price_inr": expected_f,
                "detected_price_inr": round(float(detected), 2),
                "variance_inr": variance,
                "status": "compliant" if ok else "non_compliant",
            }
        )

    if checked == 0:
        return {
            "state": "not_observable",
            "compliance_percent": None,
            "lines": lines,
            "methodology": "Price tags not readable in image — configure MRP on planogram for future OCR match.",
        }

    pct = round(compliant / checked * 100, 1)
    return {
        "state": "available",
        "compliance_percent": pct,
        "checked_tags": checked,
        "compliant_tags": compliant,
        "lines": lines,
        "methodology": f"Compared OCR-detected shelf prices to planogram MRP (±₹{tolerance_inr:.0f} tolerance).",
    }
