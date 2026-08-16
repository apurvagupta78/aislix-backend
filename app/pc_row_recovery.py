"""Recover unknown personal-care facings only when pack OCR supports the neighbor label."""

from __future__ import annotations

import re
from typing import Any

from app.planogram_guided import cluster_records_by_shelf_row
from app.pc_pack_text_guard import infer_pc_product_type, pc_pack_text_conflicts_label

PC_ROW_BRANDS = frozenset(
    {
        "dove",
        "pantene",
        "nivea",
        "tresemme",
        "head",
        "sunsilk",
        "loreal",
        "dabur",
        "himalaya",
        "pears",
        "lux",
        "lifebuoy",
        "colgate",
        "closeup",
        "axe",
        "fogg",
        "gillette",
        "ponds",
        "vaseline",
        "medimix",
        "garnier",
        "oldspice",
        "parkavenue",
        "clinic",
        "meera",
        "joy",
        "mamaearth",
        "simple",
        "wildstone",
        "lux",
        "lifebuoy",
        "santoor",
        "dettol",
        "rexona",
        "cintol",
        "himalaya",
        "clean",
    }
)


def _norm_brand(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def _is_unknown(rec: dict) -> bool:
    brand = _norm_brand(rec.get("brand") or "")
    product = (rec.get("product_name") or "").lower()
    if brand in {"", "unknown"}:
        return True
    return product in {"", "unknown", "unidentified sku"}


def _pc_aisle_enabled(scan_context: dict | None) -> bool:
    if not scan_context:
        return False
    from app.scan_context import _normalize_key

    cat = _normalize_key(scan_context.get("aislix_category") or "")
    if cat == "personal care":
        return True
    return bool(scan_context.get("multi_sub_category_audit"))


def _row_type_consensus(cluster: list[dict]) -> str | None:
    """Dominant PC product type on a shelf row (pack OCR weighted over labels)."""
    votes: dict[str, int] = {}
    for rec in cluster:
        pack = (rec.get("pack_text") or "").strip()
        pack_type = infer_pc_product_type(pack) if len(pack) >= 3 else None
        if pack_type:
            votes[pack_type] = votes.get(pack_type, 0) + 2
            continue
        if _is_unknown(rec):
            continue
        label_type = infer_pc_product_type(
            f"{rec.get('brand') or ''} {rec.get('product_name') or ''}"
        )
        if label_type:
            votes[label_type] = votes.get(label_type, 0) + 1
    if not votes:
        return None
    majority = max(votes, key=votes.get)
    if votes[majority] / sum(votes.values()) < 0.6:
        return None
    return majority


def _pack_supports_neighbor(pack_text: str, ref: dict) -> bool:
    """Only copy neighbor label when pack OCR mentions the brand and product kind agrees."""
    pack = (pack_text or "").lower()
    if len(pack.strip()) < 3:
        return False

    ref_brand = _norm_brand(ref.get("brand") or "")
    if not ref_brand:
        return False

    brand_in_pack = ref_brand in re.sub(r"[^a-z0-9]", "", pack)
    if not brand_in_pack and ref_brand not in pack:
        brand_tokens = (ref.get("brand") or "").lower().split()
        if not any(len(t) >= 4 and t in pack for t in brand_tokens):
            return False

    if pc_pack_text_conflicts_label(ref, pack_text):
        return False

    pack_type = infer_pc_product_type(pack_text)
    ref_type = infer_pc_product_type(
        f"{ref.get('brand') or ''} {ref.get('product_name') or ''}"
    )
    if pack_type and ref_type and pack_type != ref_type:
        return False

    return True


def _pack_or_row_supports_neighbor(pack_text: str, ref: dict, row_type: str | None) -> bool:
    """Copy neighbor when pack agrees, or row type is unimodal and neighbor matches row type."""
    if _pack_supports_neighbor(pack_text, ref):
        return True
    if len((pack_text or "").strip()) >= 3:
        return False
    if not row_type:
        return False
    ref_type = infer_pc_product_type(f"{ref.get('brand') or ''} {ref.get('product_name') or ''}")
    return ref_type == row_type


def recover_pc_unknowns_by_row(
    classified: list[dict],
    scan_context: dict | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Assign unknown facings only when pack OCR supports a same-row neighbor label."""
    stats: dict[str, Any] = {"pc_row_recovery": 0}
    if not _pc_aisle_enabled(scan_context):
        return classified, stats

    for cluster in cluster_records_by_shelf_row(classified):
        if len(cluster) < 2:
            continue
        labeled: dict[str, dict] = {}
        labeled_by_type: dict[str, dict] = {}
        for rec in cluster:
            if _is_unknown(rec):
                continue
            brand = _norm_brand(rec.get("brand") or "")
            if brand in PC_ROW_BRANDS:
                labeled.setdefault(brand, rec)
                ptype = infer_pc_product_type(
                    f"{rec.get('brand') or ''} {rec.get('product_name') or ''}"
                )
                if ptype:
                    labeled_by_type.setdefault(ptype, rec)

        if not labeled:
            continue

        row_type = _row_type_consensus(cluster)

        for rec in cluster:
            if not _is_unknown(rec):
                continue
            pack = rec.get("pack_text") or ""
            pack_type = infer_pc_product_type(pack) or row_type
            matched: dict | None = None
            if pack_type and pack_type in labeled_by_type:
                ref = labeled_by_type[pack_type]
                if _pack_or_row_supports_neighbor(pack, ref, row_type):
                    matched = ref
            if not matched:
                for brand, ref in labeled.items():
                    if _pack_or_row_supports_neighbor(pack, ref, row_type):
                        matched = ref
                        break
            if not matched:
                continue
            rec.update(
                {
                    "brand": matched["brand"],
                    "product_name": matched["product_name"],
                    "sku": matched.get("sku") or "",
                    "category": matched.get("category") or "Personal Care",
                    "confidence": max(float(rec.get("confidence") or 0), 0.82),
                    "recognition_source": "pc_row_neighbor",
                }
            )
            stats["pc_row_recovery"] += 1

    if stats["pc_row_recovery"]:
        print(f"PC row recovery: {stats['pc_row_recovery']} facings from pack-supported neighbors")
    return classified, stats
