"""Optional Luna secondary vision step (prices, promotions, shelf issues)."""

from __future__ import annotations

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


def luna_required(metadata: dict[str, Any]) -> bool:
    if metadata.get("enable_luna_secondary") is True:
        return True
    if metadata.get("luna_secondary") is True:
        return True

    template_fields = metadata.get("template_fields") or metadata.get("audit_template_fields") or []
    if isinstance(template_fields, list):
        for field in template_fields:
            if not isinstance(field, dict):
                continue
            field_type = str(field.get("field_type") or field.get("type") or "").strip().lower()
            if field_type in LUNA_FIELD_TYPES:
                return True
    return False


def run_luna_secondary_scan(*_args: Any, **_kwargs: Any) -> dict[str, Any] | None:
    """Placeholder — Luna integration runs when explicitly enabled and wired."""
    return None
