"""Metric state helpers — never treat missing configuration as zero performance."""

from __future__ import annotations

from typing import Any

VALID_STATES = frozenset(
    {
        "available",
        "calculated",
        "estimated",
        "not_configured",
        "insufficient_evidence",
        "not_applicable",
        "unavailable",
    }
)


def metric_value(
    value: Any,
    state: str = "available",
    *,
    label: str | None = None,
    source: str | None = None,
) -> dict:
    st = state if state in VALID_STATES else "available"
    out: dict = {"value": value, "state": st}
    if label:
        out["label"] = label
    if source:
        out["source"] = source
    return out


def not_configured(label: str | None = None) -> dict:
    return metric_value(None, "not_configured", label=label)


def insufficient(label: str | None = None) -> dict:
    return metric_value(None, "insufficient_evidence", label=label)


def merge_gpt_metric(computed: dict, gpt: Any) -> dict:
    """Prefer backend-computed values; keep GPT state/label when value absent."""
    if not isinstance(gpt, dict):
        return computed
    merged = dict(computed)
    gpt_state = gpt.get("state")
    if isinstance(gpt_state, str) and gpt_state in VALID_STATES:
        if computed.get("value") is None and gpt_state not in ("available", "calculated"):
            merged["state"] = gpt_state
        elif computed.get("value") is not None:
            merged["state"] = "available" if gpt_state == "calculated" else computed.get("state", "available")
    if gpt.get("label") and not merged.get("label"):
        merged["label"] = gpt["label"]
    return merged


def normalize_metric_field(raw: Any, *, default_state: str = "not_configured") -> dict:
    if isinstance(raw, dict) and "state" in raw:
        state = raw.get("state") if raw.get("state") in VALID_STATES else default_state
        return {"value": raw.get("value"), "state": state, **{k: v for k, v in raw.items() if k not in ("value", "state")}}
    if isinstance(raw, (int, float)):
        return metric_value(raw, "available")
    if raw is None:
        return metric_value(None, default_state)
    return metric_value(raw, "available")
