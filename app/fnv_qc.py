"""FNV QC vision result shaping — disposition JSON, not shelf inventory."""

from __future__ import annotations

from typing import Any


_DISPOSITIONS = {"SELLABLE", "DAMAGED", "HUMAN_REVIEW"}


def is_fnv_qc_metadata(metadata: dict[str, Any] | None) -> bool:
    meta = metadata or {}
    mode = str(meta.get("analysis_mode") or "").strip().lower()
    purpose = str(meta.get("purpose") or "").strip().lower()
    return mode == "fnv_qc" or purpose == "fnv_qc"


def normalize_fnv_qc_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure analysis_mode is fnv_qc when purpose requests QC."""
    meta = dict(metadata or {})
    if is_fnv_qc_metadata(meta):
        meta["analysis_mode"] = "fnv_qc"
        meta["purpose"] = "fnv_qc"
        # Never reuse shelf reference-cache hits for QC disposition.
        meta["skip_reference_cache"] = "1"
    return meta


def _coerce_disposition(raw: Any) -> str:
    text = str(raw or "HUMAN_REVIEW").strip().upper().replace(" ", "_")
    return text if text in _DISPOSITIONS else "HUMAN_REVIEW"


def finalize_fnv_qc_result(
    *,
    scan_id: str,
    parsed: dict[str, Any],
    processing_ms: int,
) -> dict[str, Any]:
    """
    Build an API payload from Astra FNV disposition JSON.

    Must NOT run shelf finalize_make_scan — FNV responses have no inventory/facings.
    """
    raw = parsed.get("raw") if isinstance(parsed, dict) else None
    if not isinstance(raw, dict):
        raw = parsed if isinstance(parsed, dict) else {}

    nested = raw.get("fnv_qc") if isinstance(raw.get("fnv_qc"), dict) else None
    src = nested if nested else raw

    disposition = _coerce_disposition(src.get("disposition") or src.get("qc_disposition"))
    defects_raw = src.get("defect_types") or src.get("defects") or []
    defect_types = (
        [str(d).strip() for d in defects_raw if str(d).strip()]
        if isinstance(defects_raw, list)
        else []
    )
    if disposition == "SELLABLE":
        defect_types = []

    conf_raw = src.get("confidence")
    try:
        confidence = float(conf_raw) if conf_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        confidence = max(0.0, min(1.0, confidence))

    product = src.get("product")
    category = src.get("category")
    notes = src.get("notes")

    fnv_block = {
        "product": str(product) if product is not None else None,
        "category": str(category) if category is not None else None,
        "disposition": disposition,
        "defect_types": defect_types,
        "confidence": confidence,
        "notes": str(notes) if notes is not None else None,
    }

    return {
        "scan_id": scan_id,
        "status": "completed",
        "analysis_mode": "fnv_qc",
        "disposition": disposition,
        "qc_disposition": disposition,
        "product": fnv_block["product"],
        "category": fnv_block["category"],
        "defect_types": defect_types,
        "confidence": confidence,
        "notes": fnv_block["notes"],
        "fnv_qc": fnv_block,
        "products": [],
        "metrics": {
            "analysis_mode": "fnv_qc",
            "processing_ms": int(processing_ms),
            "total_products": 0,
        },
        "processing_ms": int(processing_ms),
    }
