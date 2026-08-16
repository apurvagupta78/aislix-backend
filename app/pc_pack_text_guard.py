"""Personal-care labels must match pack OCR — block shampoo leakage onto soap/deo rows."""

from __future__ import annotations

import re
from typing import Any

# Ordered: more specific PC types first (deodorant before generic skincare "roll on").
_PC_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "toothpaste",
        (
            "toothpaste",
            "tooth brush",
            "toothbrush",
            "oral care",
            "dental",
            "colgate",
            "closeup",
            "pepsodent",
            "sensodyne",
        ),
    ),
    (
        "deodorant",
        (
            "deodorant",
            "deodrant",
            "body spray",
            "antiperspirant",
            "roll on",
            "roll-on",
            "park avenue",
            "wild stone",
            "fogg",
            "axe",
            "old spice",
        ),
    ),
    (
        "soap",
        (
            "soap",
            "bathing bar",
            "bath bar",
            "beauty bar",
            "pure and gentle",
            "germ shield",
            "medimix",
            "ayurvedic soap",
            "lifebuoy",
            "lux",
            "pears",
            "santoor",
            "hamam",
        ),
    ),
    (
        "shampoo",
        (
            "shampoo",
            "conditioner",
            "anti dandruff",
            "anti-dandruff",
            "hair fall",
            "hairfall",
            "head & shoulders",
            "head and shoulders",
            "pantene",
            "sunsilk",
            "tresemme",
            "keratin",
            "hyaluron",
            "vatika",
            "clinic plus",
        ),
    ),
    (
        "skincare",
        (
            "body lotion",
            "face wash",
            "facewash",
            "moistur",
            "sunscreen",
            "spf",
            "vaseline",
            "ponds",
            "nivea soft",
            "natural glow",
            "body milk",
        ),
    ),
    (
        "shaving",
        ("shaving", "shave foam", "shave gel", "razor", "gillette", "aftershave"),
    ),
)

# Weak fragments must not infer shampoo on their own.
_WEAK_SHAMPOO_FRAGMENTS = frozenset(
    {
        "poo",
        "sham",
        "shamp",
        "anti d",
        "anti d.",
        "anti da",
        "anti dandr",
        "dandruff solutions",
        "repair",
        "intense re",
        "intense repair",
    }
)

_PROPAGATION_SOURCES = frozenset(
    {
        "propagate",
        "propagate+context",
        "propagate+ice_cream_fix",
        "pc_row_neighbor",
        "faiss",
        "learned",
        "gpt",
        "gpt+ocr",
    }
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def infer_pc_product_type(text: str) -> str | None:
    """Infer PC product kind from pack OCR or label text."""
    blob = _norm(text)
    if len(blob) < 2:
        return None
    if blob in _WEAK_SHAMPOO_FRAGMENTS:
        return None
    if re.fullmatch(r"(anti|sham|poo|repair|smooth|shine|health|nourish)[a-z .]{0,12}", blob):
        return None

    best_type: str | None = None
    best_score = 0
    for ptype, markers in _PC_TYPE_RULES:
        score = sum(1 for marker in markers if marker in blob)
        if score > best_score:
            best_score = score
            best_type = ptype
    return best_type if best_score > 0 else None


def _label_blob(label: dict) -> str:
    return _norm(
        " ".join(
            filter(
                None,
                [
                    label.get("brand") or "",
                    label.get("product_name") or "",
                    label.get("variant") or "",
                    label.get("sku") or "",
                ],
            )
        )
    )


def pc_pack_text_conflicts_label(label: dict, pack_text: str) -> bool:
    """True when readable pack text indicates a different product kind than the label."""
    pack = _norm(pack_text)
    if len(pack) < 3:
        return False

    pack_type = infer_pc_product_type(pack)
    label_type = infer_pc_product_type(_label_blob(label))

    if pack_type and label_type and pack_type != label_type:
        return True

    product_l = _label_blob(label)
    if pack_type == "soap" and "shampoo" in product_l:
        return True
    if pack_type == "deodorant" and "shampoo" in product_l:
        return True
    if pack_type == "shampoo" and any(token in product_l for token in ("soap", "deodorant", "body spray", "roll on")):
        return True
    if pack_type == "toothpaste" and "shampoo" in product_l:
        return True

    from app.brand_dictionary import label_conflicts_with_pack_text

    return label_conflicts_with_pack_text(label, pack_text)


def _pc_guard_enabled(scan_context: dict | None) -> bool:
    if not scan_context:
        return False
    from app.scan_context import _normalize_key

    cat = _normalize_key(scan_context.get("aislix_category") or "")
    if cat == "personal care":
        return True
    return bool(scan_context.get("multi_sub_category_audit"))


def _is_unknown_label(rec: dict) -> bool:
    brand = (rec.get("brand") or "").strip().lower()
    product = (rec.get("product_name") or "").strip().lower()
    if brand in {"", "unknown", "n/a"}:
        return True
    return product in {"", "unknown", "unidentified sku", "n/a"}


def _demote_unknown(rec: dict) -> None:
    rec.update(
        {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "sku": "",
            "confidence": min(float(rec.get("confidence") or 0.35), 0.4),
            "recognition_source": "pc_pack_text_reject",
        }
    )


def enforce_pc_pack_text_labels(
    classified: list[dict],
    scan_context: dict | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    Reconcile PC facings with pack OCR.
    Shampoo labels are rejected on soap/deodorant/skincare packs; prefer match_from_text(pack).
    """
    stats: dict[str, Any] = {"pc_pack_text_fix": 0, "pc_pack_text_reject": 0}
    if not _pc_guard_enabled(scan_context):
        return classified, stats

    from app.brand_dictionary import label_conflicts_with_pack_text, match_from_text

    for rec in classified:
        if _is_unknown_label(rec):
            continue

        pack = (rec.get("pack_text") or "").strip()
        source = (rec.get("recognition_source") or "").lower()

        # No readable pack text: do not trust cross-facing propagation on multi-row PC shelves.
        shelf_mode = (scan_context or {}).get("shelf_mode") or ""
        if len(pack) < 3 and source in _PROPAGATION_SOURCES and shelf_mode not in {
            "single_row",
            "single_bin",
        }:
            _demote_unknown(rec)
            stats["pc_pack_text_reject"] += 1
            continue

        if len(pack) < 3:
            continue

        if not pc_pack_text_conflicts_label(rec, pack) and not label_conflicts_with_pack_text(rec, pack):
            continue

        corrected = match_from_text(pack, scan_context=scan_context)
        if (
            corrected
            and not pc_pack_text_conflicts_label(corrected, pack)
            and not label_conflicts_with_pack_text(corrected, pack)
        ):
            rec.update(
                {
                    **corrected,
                    "confidence": max(float(rec.get("confidence") or 0), float(corrected.get("confidence") or 0.85)),
                    "recognition_source": (source or "ocr") + "+pc_pack_fix",
                }
            )
            stats["pc_pack_text_fix"] += 1
            continue

        _demote_unknown(rec)
        stats["pc_pack_text_reject"] += 1

    total = stats["pc_pack_text_fix"] + stats["pc_pack_text_reject"]
    if total:
        print(
            f"PC pack-text guard: fixed {stats['pc_pack_text_fix']}, "
            f"rejected {stats['pc_pack_text_reject']} facing(s)"
        )
    return classified, stats


def pc_propagation_allowed(
    ref_label: dict,
    pack_text: str,
    scan_context: dict | None,
) -> bool:
    """Block visual propagation when pack OCR indicates a different PC product kind."""
    if not _pc_guard_enabled(scan_context):
        return True
    pack = _norm(pack_text)
    if len(pack) < 3:
        return False
    if pc_pack_text_conflicts_label(ref_label, pack_text):
        return False
    from app.scan_context import propagation_type_conflict

    return not propagation_type_conflict(ref_label, pack_text)
