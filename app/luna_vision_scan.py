"""Optional Luna secondary vision step (prices, promotions, shelf issues)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

LUNA_FIELD_TYPES = frozenset(
    {
        "visible_price",
        "visible_prices",
        "promotion",
        "promotions",
        "shelf_issue",
        "shelf_issues",
        "price_compliance",
    }
)

_PRICE_RE = re.compile(
    r"(?:₹|rs\.?\s*|inr\s*)?\s*(\d{1,5}(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)


def _truthy_flag(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def luna_required(metadata: dict[str, Any]) -> bool:
    if _truthy_flag(metadata.get("enable_luna_secondary")):
        return True
    if _truthy_flag(metadata.get("luna_secondary")):
        return True

    mode = str(metadata.get("analysis_mode") or "").strip().lower()
    if mode in {"planogram_comparison", "with_planogram"}:
        # Planogram audits usually include MRP / price compliance expectations.
        return True

    template_fields = metadata.get("template_fields") or metadata.get("audit_template_fields") or []
    if isinstance(template_fields, list):
        for field in template_fields:
            if not isinstance(field, dict):
                continue
            field_type = str(field.get("field_type") or field.get("type") or "").strip().lower()
            if field_type in LUNA_FIELD_TYPES:
                return True

    planogram_items = metadata.get("planogram_items") or []
    if isinstance(planogram_items, list):
        for item in planogram_items:
            if not isinstance(item, dict):
                continue
            if item.get("mrp_inr") not in (None, ""):
                return True
    return False


def _extract_price_candidates(text: str) -> list[float]:
    values: list[float] = []
    for match in _PRICE_RE.finditer(text or ""):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        if 0.5 <= value <= 50000:
            values.append(value)
    return values


def _derive_luna_from_astra(astra_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Luna block from Astra CV notes/fields when a second vision pass is unavailable."""
    products = [row for row in (astra_payload.get("products") or []) if isinstance(row, dict)]
    visible_prices: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    shelf_issues: list[dict[str, Any]] = []

    for product in products:
        brand = str(product.get("brand") or "").strip()
        name = str(product.get("product_name") or product.get("product") or "").strip()
        notes = str(product.get("visual_notes") or product.get("evidence_note") or "")
        label = " ".join(part for part in (brand, name) if part and part.upper() != "UNVERIFIABLE")

        explicit_price = product.get("visible_price") or product.get("price") or product.get("mrp_inr")
        if explicit_price not in (None, ""):
            try:
                visible_prices.append(
                    {
                        "product": label or brand or "unknown",
                        "brand": brand or None,
                        "price": float(explicit_price),
                        "source": "astra_field",
                    }
                )
            except (TypeError, ValueError):
                pass
        else:
            for price in _extract_price_candidates(notes)[:1]:
                visible_prices.append(
                    {
                        "product": label or brand or "unknown",
                        "brand": brand or None,
                        "price": price,
                        "source": "astra_visual_notes",
                        "note": notes[:240],
                    }
                )

        promo = product.get("promotion") or product.get("promo_text")
        if promo:
            promotions.append({"product": label or brand or "unknown", "text": str(promo)})
        elif re.search(r"\b(promo|promotion|offer|discount|bogo|%\s*off)\b", notes, re.I):
            promotions.append({"product": label or brand or "unknown", "text": notes[:240], "source": "astra_visual_notes"})

        issue = product.get("shelf_issue")
        if issue:
            shelf_issues.append({"description": str(issue), "product": label or brand or None})

    raw_issues = astra_payload.get("shelf_issues") or []
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if isinstance(issue, str) and issue.strip():
                shelf_issues.append({"description": issue.strip()})
            elif isinstance(issue, dict) and issue.get("description"):
                shelf_issues.append(issue)

    return {
        "status": "derived_from_astra",
        "source": "astra_cv",
        "visible_prices": visible_prices,
        "promotions": promotions,
        "shelf_issues": shelf_issues,
        "notes": (
            "Luna secondary analysis derived from Astra CV fields/notes. "
            "Enable LUNA_SECONDARY_VISION=1 for a dedicated secondary vision pass."
        ),
    }


def _run_luna_vision(image: Any, metadata: dict[str, Any], astra_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Optional dedicated OpenAI pass for prices/promotions."""
    if not _truthy_flag(os.getenv("LUNA_SECONDARY_VISION", "false")):
        return None
    if image is None:
        return None
    try:
        from app.openai_vision_scan import get_client, vision_jpeg_quality, vision_max_image_px
        import base64
        import cv2
        import numpy as np
    except Exception:
        return None

    try:
        arr = image if isinstance(image, np.ndarray) else None
        if arr is None:
            return None
        max_px = vision_max_image_px()
        h, w = arr.shape[:2]
        scale = min(1.0, float(max_px) / float(max(h, w)))
        if scale < 1.0:
            arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), vision_jpeg_quality()])
        if not ok:
            return None
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        prompt = (
            "You are Luna, Aislix secondary shelf vision. Return ONLY JSON with keys "
            "visible_prices (array of {brand, product, price, currency}), "
            "promotions (array of {brand, product, text}), "
            "shelf_issues (array of {description}). "
            "Read only clearly visible price tags and promo stickers. "
            "If none are readable, return empty arrays."
        )
        response = get_client().responses.create(
            model=os.getenv("LUNA_VISION_MODEL") or os.getenv("OPENAI_VISION_MODEL", "gpt-6-astra"),
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
                    ],
                }
            ],
            timeout=float(os.getenv("LUNA_VISION_TIMEOUT_SECONDS", "60")),
        )
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            return None
        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return {
            "status": "vision",
            "source": "luna_vision",
            "visible_prices": parsed.get("visible_prices") or [],
            "promotions": parsed.get("promotions") or [],
            "shelf_issues": parsed.get("shelf_issues") or [],
        }
    except Exception as exc:
        print(f"Luna secondary vision failed: {exc!r}")
        return None


def run_luna_secondary_scan(
    astra_payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    *args: Any,
    image: Any = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """
    Run Luna secondary analysis.

    Always returns a structured object when required callers invoke it, so metrics
    no longer show a silent null stub. Prefer optional dedicated vision when enabled;
    otherwise derive price/promo signals from Astra CV notes/fields.
    """
    metadata = metadata or {}
    astra_payload = astra_payload if isinstance(astra_payload, dict) else {}
    image = image if image is not None else kwargs.get("image")

    vision = _run_luna_vision(image, metadata, astra_payload)
    if vision:
        return vision
    return _derive_luna_from_astra(astra_payload)
