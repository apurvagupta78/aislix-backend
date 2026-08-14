"""Planogram-guided recognition: constrain labels to expected SKUs only."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

from app.inventory import _normalize_brand_key
from app.learned_catalog import metadata_to_sku
from app.ocr_reader import classify_with_ocr, read_packaging_text
from app.planogram_compliance import _brand_key, _norm, _text_has_kind, _token_overlap
from app.planogram_csv import build_match_key

PLANOGRAM_MATCH_MIN_SCORE = 0.38
PLANOGRAM_SLOT_MIN_SCORE = 0.22
PLANOGRAM_LEARN_MIN_CONFIDENCE = 0.55
PLANOGRAM_POSITIONAL_FALLBACK_MIN_SCORE = 0.28

# Product tokens for planogram OCR scoring (beyond shampoo).
_PLANOGRAM_PRODUCT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ice cream": (
        "ice cream", "kulfi", "rajbhog", "rajwadi", "rabdi", "sandwich", "funwich", "funwith",
        "tricone", "sorbet", "gelato", "raspberry", "rasberry", "chocolate", "brooklyn", "baskin",
    ),
    "ice_cream": (
        "ice cream", "kulfi", "rajbhog", "rajwadi", "rabdi", "sandwich", "funwich", "funwith",
        "tricone", "sorbet", "gelato", "raspberry", "rasberry", "chocolate", "brooklyn", "baskin",
    ),
    "chips": ("chips", "crisps", "wafers", "nacho", "masala", "barbecue", "classic", "limon", "limón", "tomato", "tango", "cream", "onion"),
    "potato_chips": ("chips", "crisps", "wafers", "potato", "classic", "barbecue", "salted", "magic masala", "tomato", "tango", "cream", "onion"),
    "tortilla_chips": ("doritos", "nacho", "tortilla", "sweet chili", "sweet chilli", "cheese"),
    "extruded_snacks": ("kurkure", "cheetos", "bingo", "masala munch", "chatka", "angles", "crunchem"),
    "namkeen": ("namkeen", "bhujia", "balaji", "haldiram", "mast", "masti"),
}


def _x_center_rec(record: dict) -> float:
    return (float(record["x1"]) + float(record["x2"])) / 2.0


def _y_center_rec(record: dict) -> float:
    return (float(record["y1"]) + float(record["y2"])) / 2.0


def _record_height(record: dict) -> float:
    return max(0.0, float(record["y2"]) - float(record["y1"]))


_SHELF_POSITION_RE = re.compile(r"shelf\s*(\d+)", re.IGNORECASE)


def parse_shelf_number(shelf_position: str | None) -> int | None:
    """Extract shelf index from planogram shelf_position (e.g. 'Shelf 2 / Position 1-2')."""
    if not shelf_position:
        return None
    match = _SHELF_POSITION_RE.search(str(shelf_position))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _same_bottle_column_records(a: dict, b: dict) -> bool:
    ax1, ax2 = float(a["x1"]), float(a["x2"])
    bx1, bx2 = float(b["x1"]), float(b["x2"])
    ix1, ix2 = max(ax1, bx1), min(ax2, bx2)
    if ix2 <= ix1:
        gap = abs(_x_center_rec(a) - _x_center_rec(b))
        return gap <= min(ax2 - ax1, bx2 - bx1) * 0.38
    overlap = ix2 - ix1
    narrower = min(ax2 - ax1, bx2 - bx1)
    if narrower <= 0:
        return False
    if overlap / narrower >= 0.28:
        return True
    return abs(_x_center_rec(a) - _x_center_rec(b)) <= narrower * 0.38


def cluster_records_by_column(records: list[dict]) -> list[list[dict]]:
    """Group facings into bottle columns left-to-right."""
    if not records:
        return []
    if len(records) == 1:
        return [records]
    ordered = sorted(records, key=_x_center_rec)
    clusters: list[list[dict]] = [[ordered[0]]]
    for rec in ordered[1:]:
        if _same_bottle_column_records(clusters[-1][-1], rec):
            clusters[-1].append(rec)
        else:
            clusters.append([rec])
    return clusters


def _same_shelf_row_records(a: dict, b: dict, median_h: float) -> bool:
    """True when two facings sit on the same horizontal shelf row."""
    threshold = max(median_h * 0.42, 18.0)
    return abs(_y_center_rec(a) - _y_center_rec(b)) <= threshold


def cluster_records_by_shelf_row(records: list[dict]) -> list[list[dict]]:
    """Group facings into shelf rows top-to-bottom (multi-row snack racks)."""
    if not records:
        return []
    if len(records) == 1:
        return [records]
    ordered = sorted(records, key=_y_center_rec)
    heights = sorted(_record_height(r) for r in records if _record_height(r) > 0)
    median_h = heights[len(heights) // 2] if heights else 80.0
    clusters: list[list[dict]] = [[ordered[0]]]
    for rec in ordered[1:]:
        if _same_shelf_row_records(clusters[-1][-1], rec, median_h):
            clusters[-1].append(rec)
        else:
            clusters.append([rec])
    return [sorted(row, key=_x_center_rec) for row in clusters]


def _product_key(row: dict) -> tuple[str, str]:
    return (
        _norm(row.get("brand") or ""),
        _norm(row.get("product_name") or row.get("product") or ""),
    )


def unique_planogram_products_in_order(candidates: list[dict]) -> list[dict]:
    """Unique planogram SKUs in CSV/API order (slot-level duplicates collapsed)."""
    seen: set[tuple[str, str]] = set()
    ordered: list[dict] = []
    for row in candidates:
        key = _product_key(row)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        ordered.append(row)
    return ordered


def planogram_visual_rows(candidates: list[dict]) -> list[dict]:
    """
    One representative SKU per physical shelf band, top to bottom.
    Uses shelf_position when present; otherwise consecutive product runs or unique SKUs.
    """
    if not candidates:
        return []
    by_shelf: dict[int, dict] = {}
    for row in candidates:
        shelf_num = parse_shelf_number(row.get("shelf_position"))
        if shelf_num is not None and shelf_num not in by_shelf:
            by_shelf[shelf_num] = row
    if len(by_shelf) >= 2:
        return [by_shelf[k] for k in sorted(by_shelf.keys())]

    visual: list[dict] = []
    prev_key: tuple[str, str] | None = None
    for row in candidates:
        key = _product_key(row)
        if key != prev_key and key[0]:
            visual.append(row)
            prev_key = key
    if len(visual) >= 2:
        return visual
    return unique_planogram_products_in_order(candidates)


def planogram_products_by_shelf(candidates: list[dict]) -> dict[int, dict]:
    """Map planogram shelf number → representative SKU row."""
    by_shelf: dict[int, dict] = {}
    for row in candidates:
        shelf_num = parse_shelf_number(row.get("shelf_position"))
        if shelf_num is None or shelf_num in by_shelf:
            continue
        by_shelf[shelf_num] = row
    return by_shelf


def _expected_qty_for_product(candidates: list[dict], product_row: dict) -> int:
    key = _product_key(product_row)
    total = sum(
        int(row.get("expected_qty") or 1)
        for row in candidates
        if _product_key(row) == key
    )
    return max(total, 1)


def allocate_cluster_candidates(candidates: list[dict], n_clusters: int) -> list[dict | None]:
    """Map each detected shelf-row cluster to a planogram candidate (bottom-aligned)."""
    if n_clusters <= 0:
        return []
    visual = planogram_visual_rows(candidates)
    if not visual:
        return [None] * n_clusters

    if len(visual) == n_clusters:
        return visual

    if len(visual) > n_clusters:
        offset = len(visual) - n_clusters
        return visual[offset:]

    weights = [_expected_qty_for_product(candidates, row) for row in visual]
    total_w = sum(weights) or len(visual)
    allocation: list[dict] = []
    remaining = n_clusters
    for i, (row, weight) in enumerate(zip(visual, weights)):
        if i == len(visual) - 1:
            count = max(1, remaining)
        else:
            count = max(1, round(n_clusters * weight / total_w))
            remaining -= count
        allocation.extend([row] * count)

    if len(allocation) < n_clusters:
        allocation.extend([visual[-1]] * (n_clusters - len(allocation)))
    return allocation[:n_clusters]


def align_shelf_clusters_to_planogram(n_clusters: int, shelf_numbers: list[int]) -> dict[int, int]:
    """
    Map visual row cluster index (0=top) to planogram shelf number.
    Bottom-align when the photo includes an extra partial row above the planogram.
    """
    if n_clusters <= 0 or not shelf_numbers:
        return {}
    shelf_numbers = sorted(shelf_numbers)
    mapping: dict[int, int] = {}
    if n_clusters == len(shelf_numbers):
        for idx, shelf_num in enumerate(shelf_numbers):
            mapping[idx] = shelf_num
    elif n_clusters > len(shelf_numbers):
        offset = n_clusters - len(shelf_numbers)
        for idx, shelf_num in enumerate(shelf_numbers):
            mapping[offset + idx] = shelf_num
    else:
        for idx in range(n_clusters):
            mapping[idx] = shelf_numbers[idx]
    return mapping


def _union_record_box(records: list[dict]) -> dict:
    base = dict(records[0])
    base["x1"] = min(float(r["x1"]) for r in records)
    base["y1"] = min(float(r["y1"]) for r in records)
    base["x2"] = max(float(r["x2"]) for r in records)
    base["y2"] = max(float(r["y2"]) for r in records)
    return base


def _is_unknown_record(record: dict) -> bool:
    brand = _norm(record.get("brand") or "")
    product = _norm(record.get("product_name") or record.get("name") or "")
    return brand in {"", "unknown"} or product in {"", "unknown", "unidentified sku"}


def _pick_best_in_slot(slot: list[dict]) -> dict:
    def rank(rec: dict) -> tuple:
        unknown = _is_unknown_record(rec)
        conf = float(rec.get("confidence") or 0)
        area = max(0.0, float(rec["x2"]) - float(rec["x1"])) * max(0.0, float(rec["y2"]) - float(rec["y1"]))
        return (0 if unknown else 1, conf, area)

    return max(slot, key=rank)


def prepare_planogram_candidates(
    planogram_items: list[dict],
    scope_type: str | None,
    scope_values: dict | None,
    scan_context: dict | None,
) -> list[dict]:
    """Filter planogram rows to assignment scope for closed-vocabulary recognition."""
    from app.planogram_compliance import filter_planogram_by_scope

    scoped = filter_planogram_by_scope(planogram_items, scope_type, scope_values, scan_context)
    return [_normalize_candidate(row) for row in scoped if row.get("brand")]


def _normalize_candidate(row: dict) -> dict:
    brand = str(row.get("brand") or "").strip()
    product = str(row.get("product_name") or row.get("product") or "").strip()
    return {
        **row,
        "brand": brand,
        "product_name": product,
        "expected_qty": int(row.get("expected_qty") or 1),
        "match_key": row.get("match_key") or build_match_key(
            brand, product, str(row.get("sku") or ""), str(row.get("sub_category") or "")
        ),
        "category": row.get("category") or "",
        "sub_category": row.get("sub_category") or "",
    }


def _ocr_brand_conflicts(text: str, candidate: dict) -> bool:
    """True when pack text clearly names a different brand than the planogram row."""
    if not text or not text.strip():
        return False
    blob = _norm(text)
    cand_brand = _norm(candidate.get("brand") or "")
    if not cand_brand:
        return False
    hints: list[tuple[str, str]] = [
        (r"\bamul\b", "amul"),
        (r"\bbaskin\b|\bfunwich\b|\bfunwith\b", "baskin"),
        (r"\bbrooklyn\b", "brooklyn"),
        (r"\bhavmor\b", "havmor"),
        (r"\bdove\b", "dove"),
        (r"\bclinic\s*plus\b|\bclinic\b", "clinic"),
        (r"\bhimalaya\b", "himalaya"),
        (r"\blay'?s\b|\blays\b", "lay"),
        (r"\bdoritos\b", "doritos"),
        (r"\bkurkure\b", "kurkure"),
        (r"\bpringles\b", "pringles"),
        (r"\bruffles\b", "ruffles"),
        (r"\bcheetos\b", "cheetos"),
        (r"\bbalaji\b", "balaji"),
        (r"\bbingo\b", "bingo"),
        (r"\bhaldiram", "haldiram"),
        (r"\buncle\s*chipps?\b", "uncle"),
    ]
    for pattern, hinted in hints:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            if hinted not in cand_brand and cand_brand not in hinted:
                if not any(token in blob for token in cand_brand.split()):
                    return True
            break
    return False


def _product_keyword_bonus(text: str, candidate: dict) -> float:
    sub = _norm(candidate.get("sub_category") or "")
    blob = _norm(text)
    if not blob:
        return 0.0
    keywords = _PLANOGRAM_PRODUCT_KEYWORDS.get(sub) or _PLANOGRAM_PRODUCT_KEYWORDS.get("ice cream", ())
    product = _norm(candidate.get("product_name") or "")
    hits = sum(1 for kw in keywords if kw in blob)
    if product:
        hits += sum(1 for token in product.split() if len(token) >= 4 and token in blob)
    return min(0.35, 0.08 * hits) if hits else 0.0


def _brand_in_text(text: str, candidate: dict) -> float:
    blob = _norm(text)
    if not blob:
        return 0.0
    brand = _norm(candidate.get("brand") or "")
    if not brand:
        return 0.0
    if brand in blob:
        return 1.0
    if "lay" in brand and re.search(r"lay'?s\b", blob, flags=re.IGNORECASE):
        return 0.95
    if "haldiram" in brand and "haldiram" in blob.replace("'", ""):
        return 0.92
    # Common OCR variants
    if "head" in blob and "shoulder" in blob and ("head" in brand or "shoulder" in brand):
        return 0.88
    if "clinic" in blob and "plus" in blob and "clinic" in brand:
        return 0.88
    if "himalaya" in blob and "himalaya" in brand:
        return 0.9
    parts = [p for p in re.split(r"[\s&]+", brand) if len(p) > 2]
    if parts and all(p in blob for p in parts):
        return 0.9
    hits = sum(1 for p in parts if p in blob)
    if hits and hits >= max(1, len(parts) - 1):
        return 0.65
    bk = _brand_key(candidate)
    if bk and bk in blob.replace(" ", ""):
        return 0.55
    return 0.0


def score_text_against_candidate(text: str, candidate: dict) -> float:
    """Score OCR/pack text against one planogram row."""
    if not text or not text.strip():
        return 0.0
    if _ocr_brand_conflicts(text, candidate):
        return 0.0
    brand_score = _brand_in_text(text, candidate)
    if brand_score <= 0.0:
        return 0.0
    product_score = _token_overlap(candidate.get("product_name") or "", text)
    sub = _norm(candidate.get("sub_category") or "")
    kind_bonus = 0.12 if sub and _text_has_kind(text, sub) else 0.0
    keyword_bonus = _product_keyword_bonus(text, candidate)
    return min(1.0, brand_score * 0.55 + product_score * 0.33 + kind_bonus + keyword_bonus)


def best_candidate_from_text(
    text: str,
    candidates: list[dict],
    min_score: float = PLANOGRAM_MATCH_MIN_SCORE,
) -> tuple[dict, float] | None:
    best: dict | None = None
    best_score = 0.0
    for row in candidates:
        if _ocr_brand_conflicts(text, row):
            continue
        score = score_text_against_candidate(text, row)
        if score > best_score:
            best_score = score
            best = row
    if best is None or best_score < min_score:
        return None
    return best, best_score


def best_candidate_from_label(
    label: dict,
    candidates: list[dict],
    ocr_text: str = "",
    min_score: float = PLANOGRAM_MATCH_MIN_SCORE,
) -> tuple[dict, float] | None:
    brand = label.get("brand") or ""
    product = label.get("product_name") or label.get("name") or ""
    combined = f"{brand} {product}".strip()
    match = best_candidate_from_text(combined, candidates, min_score=min_score * 0.85)
    if match:
        return match
    if ocr_text:
        return best_candidate_from_text(ocr_text, candidates, min_score=min_score)
    act_key = _brand_key({"brand": brand, "product_name": product})
    for row in candidates:
        if _brand_key(row) == act_key:
            return row, 0.5
        exp = _norm(row.get("brand") or "")
        if exp and exp in _norm(brand):
            return row, 0.48
    return None


def label_from_candidate(
    candidate: dict,
    confidence: float,
    source: str,
    ocr_text: str = "",
) -> dict:
    product = candidate.get("product_name") or ""
    brand = candidate.get("brand") or ""
    return {
        "brand": brand,
        "product_name": product,
        "variant": "",
        "category": candidate.get("category") or "General",
        "sub_category": candidate.get("sub_category") or "",
        "confidence": round(float(confidence), 4),
        "recognition_source": source,
        "sku": metadata_to_sku(brand, product, ""),
        "planogram_match_key": candidate.get("match_key"),
        "planogram_guided": True,
    }


def snap_label_to_planogram(
    label: dict | None,
    candidates: list[dict],
    ocr_text: str = "",
) -> dict | None:
    """Map an open-vocabulary label to the nearest planogram row, or None."""
    if not label or not candidates:
        return None
    brand = (label.get("brand") or "").strip().lower()
    if brand in {"", "unknown"}:
        match = best_candidate_from_text(ocr_text, candidates)
    else:
        match = best_candidate_from_label(label, candidates, ocr_text=ocr_text)
    if not match:
        return None
    candidate, score = match
    if ocr_text and _ocr_brand_conflicts(ocr_text, candidate):
        return None
    if ocr_text and len(ocr_text.strip()) >= 3:
        ocr_match = best_candidate_from_text(ocr_text, candidates, min_score=PLANOGRAM_MATCH_MIN_SCORE)
        if ocr_match and ocr_match[1] >= score:
            candidate, score = ocr_match
    conf = max(float(label.get("confidence") or 0.5), score)
    source = label.get("recognition_source") or "planogram_snap"
    return label_from_candidate(candidate, conf, source, ocr_text)


def planogram_gpt_prompt_block(candidates: list[dict]) -> str:
    lines = [
        "\n\nASSIGNED PLANOGRAM AUDIT — closed product list.",
        "You MUST choose exactly ONE product from this list (copy brand and product_name exactly):",
    ]
    for idx, row in enumerate(candidates, start=1):
        lines.append(
            f'{idx}. brand="{row.get("brand")}" product_name="{row.get("product_name")}" '
            f'(sub_category={row.get("sub_category") or "n/a"})'
        )
    lines.extend([
        "If the pack clearly matches one list item, return that brand and product_name verbatim.",
        'If unreadable or not on the list, return brand="Unknown" product_name="Unidentified SKU".',
        'Add field "list_index": <1-based index or null>.',
    ])
    return "\n".join(lines)


def _resolve_gpt_to_candidate(result: dict, candidates: list[dict]) -> dict | None:
    idx = result.get("list_index")
    if idx is not None:
        try:
            i = int(idx) - 1
            if 0 <= i < len(candidates):
                return candidates[i]
        except (TypeError, ValueError):
            pass
    brand = _norm(result.get("brand") or "")
    product = _norm(result.get("product_name") or "")
    for row in candidates:
        if _norm(row.get("brand") or "") == brand and _norm(row.get("product_name") or "") == product:
            return row
    match = best_candidate_from_label(result, candidates)
    return match[0] if match else None


def classify_with_planogram_gpt(
    image: Image.Image,
    candidates: list[dict],
    ocr_hint: str = "",
    scan_context: dict | None = None,
    row_hint: str = "",
) -> dict:
    from app.recognizer import GPT_MODEL, get_client
    from app.scan_context import gpt_context_prompt

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    base_prompt = (
        "You are reading one product crop from an assigned shelf audit.\n"
        "Return ONLY valid JSON:\n"
        '{\n  "brand": "",\n  "product_name": "",\n  "list_index": null,\n'
        '  "confidence": 0.0,\n  "visible_text": ""\n}\n'
    )
    hint = f"\nOCR hint: {ocr_hint}" if ocr_hint else ""
    if row_hint:
        hint += f"\nShelf context: {row_hint}"
    try:
        response = get_client().responses.create(
            model=GPT_MODEL,
            input=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": base_prompt
                        + planogram_gpt_prompt_block(candidates)
                        + gpt_context_prompt(scan_context)
                        + hint,
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{image_b64}",
                    },
                ],
            }],
        )
        result = json.loads(response.output_text)
        brand = (result.get("brand") or "").strip().lower()
        if brand in {"", "unknown"}:
            return {
                "brand": "Unknown",
                "product_name": "Unidentified SKU",
                "confidence": 0.35,
                "recognition_source": "gpt_planogram",
                "category": "General",
                "sku": "",
            }
        candidate = _resolve_gpt_to_candidate(result, candidates)
        if candidate:
            return label_from_candidate(
                candidate,
                float(result.get("confidence") or 0.82),
                "gpt_planogram",
                ocr_hint,
            )
        return {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "recognition_source": "gpt_planogram",
            "category": "General",
            "sku": "",
        }
    except Exception:
        return {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "confidence": 0.35,
            "recognition_source": "gpt_planogram",
            "category": "General",
            "sku": "",
        }


def _merge_record(record: dict, label: dict) -> dict:
    merged = {**record, **label}
    merged["confidence"] = float(label.get("confidence") or 0.35)
    if not merged.get("sku"):
        merged["sku"] = metadata_to_sku(
            merged.get("brand") or "",
            merged.get("product_name") or "",
            merged.get("variant") or "",
        )
    return merged


def classify_records_planogram_guided(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict]:
    """Recognize crops using only planogram candidate SKUs."""
    from app.clip_embeddings import embed_pil_images
    from app.faiss_matcher import is_ready, match_embeddings_batch, match_embeddings_batch_topk
    from app.recognizer import GPT_MAX_FALLBACKS, _unknown_label, recognition_v3_enabled

    scan_context = scan_context or {}
    candidates: list[dict] = scan_context.get("planogram_candidates") or []
    if not records or not candidates:
        from app.recognizer import classify_records_v3, classify_records_v2, recognition_v3_enabled as v3_on

        classify_fn = classify_records_v3 if v3_on() else classify_records_v2
        return classify_fn(records, scan_id=scan_id, scan_category=scan_category, scan_context=scan_context)

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "planogram": 0, "none": 0, "gpt_calls": 0}
    v3 = recognition_v3_enabled()
    ocr_texts: list[str] = []
    for img in images:
        pack_text = read_packaging_text(img)
        if len(pack_text.strip()) < 3:
            pack_text = read_packaging_text(img, aggressive=True)
        ocr_texts.append(pack_text)

    if v3 and is_ready():
        topk = match_embeddings_batch_topk(embeddings, scan_context=scan_context)
        for index, row_candidates in enumerate(topk):
            pack_text = ocr_texts[index]
            for match, score in row_candidates:
                if score < 0.78:
                    break
                snapped = snap_label_to_planogram(match, candidates, pack_text)
                if snapped and (pack_text.strip() or score >= 0.92):
                    snapped["confidence"] = max(snapped["confidence"], float(score) * 0.95)
                    classified[index] = _merge_record(records[index], snapped)
                    stats["faiss"] += 1
                    break

    pending: list[int] = [index for index in range(len(records)) if classified[index] is None]

    for index in pending:
        pack_text = ocr_texts[index]

        match = best_candidate_from_text(pack_text, candidates)
        if match:
            candidate, score = match
            classified[index] = _merge_record(
                records[index],
                label_from_candidate(candidate, max(0.72, score), "planogram_ocr", pack_text),
            )
            stats["planogram"] += 1
            continue

        ocr_label = classify_with_ocr(images[index], raw_text=pack_text)
        snapped = snap_label_to_planogram(ocr_label, candidates, pack_text)
        if snapped:
            classified[index] = _merge_record(records[index], snapped)
            stats["ocr"] += 1
            continue

        classified[index] = None

    pending = [index for index in range(len(records)) if classified[index] is None]

    if pending and is_ready() and not v3:
        pending_embeddings = embeddings[pending]
        matches = match_embeddings_batch(pending_embeddings, threshold=0.78, scan_context=scan_context)
        still: list[int] = []
        for local_i, index in enumerate(pending):
            match, score = matches[local_i]
            if match:
                snapped = snap_label_to_planogram(match, candidates, ocr_texts[index])
                if snapped:
                    snapped["confidence"] = max(snapped["confidence"], float(score) * 0.95)
                    classified[index] = _merge_record(records[index], snapped)
                    stats["faiss"] += 1
                    continue
            still.append(index)
        pending = still
    elif pending and is_ready() and v3:
        pending_embeddings = embeddings[pending]
        topk = match_embeddings_batch_topk(pending_embeddings, scan_context=scan_context)
        still: list[int] = []
        for local_i, index in enumerate(pending):
            snapped_label = None
            for match, score in topk[local_i]:
                if score < 0.78:
                    break
                snapped = snap_label_to_planogram(match, candidates, ocr_texts[index])
                if snapped:
                    snapped["confidence"] = max(snapped["confidence"], float(score) * 0.95)
                    snapped_label = snapped
                    break
            if snapped_label:
                classified[index] = _merge_record(records[index], snapped_label)
                stats["faiss"] += 1
            else:
                still.append(index)
        pending = still

    gpt_cap = min(GPT_MAX_FALLBACKS, len(pending))
    gpt_used = 0
    pending.sort(key=lambda idx: (0 if ocr_texts[idx].strip() else 1, idx))
    for index in pending:
        if gpt_used < gpt_cap:
            label = classify_with_planogram_gpt(
                images[index],
                candidates,
                ocr_hint=ocr_texts[index],
                scan_context=scan_context,
            )
            gpt_used += 1
            brand = (label.get("brand") or "").lower()
            if brand not in {"", "unknown"}:
                classified[index] = _merge_record(records[index], label)
                stats["gpt"] += 1
                continue
        pack_text = ocr_texts[index]
        if pack_text.strip():
            match = best_candidate_from_text(pack_text, candidates, min_score=PLANOGRAM_MATCH_MIN_SCORE)
            if match:
                candidate, score = match
                classified[index] = _merge_record(
                    records[index],
                    label_from_candidate(candidate, score, "planogram_fallback", pack_text),
                )
                stats["planogram"] += 1
                continue
        classified[index] = _merge_record(records[index], _unknown_label())
        stats["none"] += 1

    stats["gpt_calls"] = gpt_used
    stats["unknown_count"] = stats["none"]
    stats["planogram_mode"] = True
    stats["planogram_candidates"] = len(candidates)

    output = [{k: v for k, v in row.items() if k != "_index"} for row in classified if row]
    return output, stats


def should_use_planogram_shelf_rows(
    records: list[dict],
    candidates: list[dict],
    scan_context: dict | None = None,
) -> bool:
    """Multi-row snack racks: assign SKUs by horizontal shelf row (Y position)."""
    if not records or not candidates:
        return False
    if len(planogram_visual_rows(candidates)) < 2:
        return False
    from app.scan_context import CHIPS_RACK_SUBCATEGORIES, effective_sub_category

    sub = effective_sub_category(scan_context or {})
    if sub not in CHIPS_RACK_SUBCATEGORIES:
        return False
    if len(records) < 4:
        return False
    return True


def assign_planogram_shelf_rows(
    records: list[dict],
    candidates: list[dict],
    scan_id: str | None = None,
    scan_context: dict | None = None,
) -> list[dict]:
    """Label every facing on a multi-row rack from planogram shelf rows or product order."""
    if not records or not candidates:
        return records

    row_clusters = cluster_records_by_shelf_row(records)
    if not row_clusters:
        return records

    cluster_candidates = allocate_cluster_candidates(candidates, len(row_clusters))
    if not cluster_candidates:
        return records

    output: list[dict] = []
    assigned = 0
    for cluster_idx, row in enumerate(row_clusters):
        default_candidate = (
            cluster_candidates[cluster_idx]
            if cluster_idx < len(cluster_candidates)
            else None
        )
        if default_candidate is None:
            output.extend(row)
            continue

        product_key = _product_key(default_candidate)
        shelf_num = parse_shelf_number(default_candidate.get("shelf_position"))
        shelf_candidates = [
            c
            for c in candidates
            if shelf_num is not None
            and parse_shelf_number(c.get("shelf_position")) == shelf_num
        ]
        if not shelf_candidates:
            shelf_candidates = [c for c in candidates if _product_key(c) == product_key]
        if not shelf_candidates:
            shelf_candidates = [default_candidate]

        row_ocrs: list[str] = []
        for rec in row:
            path = rec.get("image_path")
            if path:
                img = Image.open(path).convert("RGB")
                text = read_packaging_text(img)
                if len(text.strip()) < 3:
                    text = read_packaging_text(img, aggressive=True)
                row_ocrs.append(text)
            else:
                row_ocrs.append("")

        merged_ocr = " ".join(token for token in row_ocrs if token.strip())
        text_match = best_candidate_from_text(
            merged_ocr,
            shelf_candidates,
            min_score=PLANOGRAM_MATCH_MIN_SCORE * 0.85,
        )
        row_candidate = text_match[0] if text_match else default_candidate
        text_score = text_match[1] if text_match else 0.0

        for rec, ocr in zip(row, row_ocrs):
            if not _is_unknown_record(rec):
                existing = best_candidate_from_label(
                    rec,
                    shelf_candidates,
                    ocr_text=ocr or merged_ocr,
                    min_score=0.45,
                )
                if existing and existing[0].get("product_name") == row_candidate.get("product_name"):
                    output.append(rec)
                    continue

            per_match = best_candidate_from_text(ocr, shelf_candidates, min_score=PLANOGRAM_MATCH_MIN_SCORE * 0.8)
            candidate = per_match[0] if per_match else row_candidate
            score = per_match[1] if per_match else text_score
            conf = max(0.74, score, float(rec.get("confidence") or 0) * 0.5)
            if ocr.strip() and re.search(r"lay'?s\b", ocr, flags=re.IGNORECASE):
                conf = max(conf, 0.84)
            source = "planogram_shelf_row_ocr" if score >= PLANOGRAM_SLOT_MIN_SCORE else "planogram_shelf_row"
            label = label_from_candidate(candidate, conf, source, ocr)
            output.append(_merge_record(rec, label))
            assigned += 1

    if assigned:
        print(
            f"Planogram shelf-row assignment: {assigned}/{len(records)} facings "
            f"({len(row_clusters)} rows, scan={scan_id})"
        )
    return output if output else records


def _facing_y_center(item: dict) -> float:
    return (float(item["y1"]) + float(item["y2"])) / 2.0


def _facing_height(item: dict) -> float:
    return max(0.0, float(item["y2"]) - float(item["y1"]))


def _shelf_row_neighbor_hint(classified: list[dict], index: int) -> str:
    """Hint GPT with products already labeled on the same shelf row."""
    from app.recognizer import _is_unknown_label

    target = classified[index]
    ty = _facing_y_center(target)
    threshold = max(_facing_height(target) * 0.42, 18.0)
    labels: list[str] = []
    for i, other in enumerate(classified):
        if i == index or _is_unknown_label(other):
            continue
        if abs(_facing_y_center(other) - ty) > threshold:
            continue
        brand = (other.get("brand") or "").strip()
        product = (other.get("product_name") or "").strip()
        if brand and product:
            labels.append(f"{brand} {product}")
    if not labels:
        return ""
    unique = list(dict.fromkeys(labels))
    return f"Same shelf row already identified as: {', '.join(unique[:3])}"


def recover_planogram_unknowns_with_gpt(
    classified: list[dict],
    scan_context: dict | None = None,
    scan_id: str | None = None,
) -> tuple[list[dict], dict]:
    """
    Second GPT pass on facings still Unknown after OCR/FAISS/shelf-row assignment.
    Uses closed planogram vocabulary + same-row neighbor hints.
    """
    from app.recognizer import GPT_MAX_FALLBACKS, _is_unknown_label, strict_gpt_fallback_enabled

    stats = {"gpt": 0, "gpt_calls": 0, "gpt_recovery": 0}
    scan_context = scan_context or {}
    candidates: list[dict] = scan_context.get("planogram_candidates") or []
    if not candidates or not strict_gpt_fallback_enabled():
        return classified, stats

    pending = [index for index, row in enumerate(classified) if _is_unknown_label(row)]
    if not pending:
        return classified, stats

    gpt_cap = min(GPT_MAX_FALLBACKS, len(pending))
    gpt_used = 0
    pending.sort(
        key=lambda idx: (
            0 if _shelf_row_neighbor_hint(classified, idx) else 1,
            idx,
        )
    )

    for index in pending:
        if gpt_used >= gpt_cap:
            break
        row = classified[index]
        path = row.get("image_path")
        if not path:
            continue
        img = Image.open(path).convert("RGB")
        ocr_hint = read_packaging_text(img)
        if len(ocr_hint.strip()) < 3:
            ocr_hint = read_packaging_text(img, aggressive=True)
        row_hint = _shelf_row_neighbor_hint(classified, index)
        label = classify_with_planogram_gpt(
            img,
            candidates,
            ocr_hint=ocr_hint,
            scan_context=scan_context,
            row_hint=row_hint,
        )
        gpt_used += 1
        if _is_unknown_label(label):
            continue
        classified[index] = _merge_record(row, label)
        stats["gpt"] += 1
        stats["gpt_recovery"] += 1

    stats["gpt_calls"] = gpt_used
    if stats["gpt_recovery"]:
        print(
            f"Planogram GPT recovery: {stats['gpt_recovery']} facing(s) "
            f"(scan={scan_id})"
        )
    return classified, stats


def should_use_planogram_slots(
    records: list[dict],
    candidates: list[dict],
    scan_context: dict | None = None,
) -> bool:
    """Planogram slot reassignment is for single-row shelves with enough detections."""
    if not records or not candidates:
        return False
    scan_context = scan_context or {}
    shelf_mode = scan_context.get("shelf_mode") or ""
    if shelf_mode in {"multi_row", "multi_bin"}:
        return False
    from app.scan_context import effective_sub_category

    sub = effective_sub_category(scan_context)
    if sub == "ice_cream" and len(records) < len(candidates):
        return False
    if len(records) < max(2, int(len(candidates) * 0.6)):
        return False
    return True


def assign_planogram_slots(
    records: list[dict],
    candidates: list[dict],
    scan_id: str | None = None,
    scan_context: dict | None = None,
) -> list[dict]:
    """One facing per planogram SKU: column cluster + greedy match + positional fallback."""
    from app.clip_embeddings import embed_pil_images
    from app.learned_catalog import learn_sku

    if not records or not candidates:
        return records

    slots = cluster_records_by_column(records)
    if not slots:
        return records

    slot_best = [_pick_best_in_slot(slot) for slot in slots]
    slot_ocrs: list[str] = []
    slot_images = []
    for best in slot_best:
        path = best.get("image_path")
        if path:
            img = Image.open(path).convert("RGB")
            slot_images.append(img)
            slot_ocrs.append(read_packaging_text(img))
        else:
            slot_images.append(None)
            slot_ocrs.append("")

    n_slots = len(slots)
    n_cand = len(candidates)
    pairs: list[tuple[float, int, int]] = []
    for si in range(n_slots):
        for ci in range(n_cand):
            score = score_text_against_candidate(slot_ocrs[si], candidates[ci])
            if not _is_unknown_record(slot_best[si]):
                label_match = best_candidate_from_label(
                    slot_best[si], [candidates[ci]], ocr_text=slot_ocrs[si], min_score=0.25
                )
                if label_match:
                    score = max(score, label_match[1])
            pairs.append((score, si, ci))
    pairs.sort(key=lambda item: item[0], reverse=True)

    slot_to_cand: dict[int, int] = {}
    used_cands: set[int] = set()
    for score, si, ci in pairs:
        if si in slot_to_cand or ci in used_cands:
            continue
        if score >= PLANOGRAM_SLOT_MIN_SCORE:
            slot_to_cand[si] = ci
            used_cands.add(ci)

    scan_context = scan_context or {}
    shelf_mode = scan_context.get("shelf_mode") or ""
    exact_row_match = (
        shelf_mode in {"single_row", "single_bin", ""}
        and n_slots == n_cand
        and n_slots >= 2
    )

    if abs(n_slots - n_cand) <= 1:
        for si in range(min(n_slots, n_cand)):
            if si in slot_to_cand or si in used_cands:
                continue
            score = score_text_against_candidate(slot_ocrs[si], candidates[si])
            if score >= PLANOGRAM_POSITIONAL_FALLBACK_MIN_SCORE or exact_row_match:
                slot_to_cand[si] = si
                used_cands.add(si)

    # Positional fallback: OCR-supported, or exact facing count on a single product row.
    slot_order = sorted(range(n_slots), key=lambda si: _x_center_rec(slot_best[si]))
    for rank, si in enumerate(slot_order):
        if si in slot_to_cand:
            continue
        if rank >= n_cand or rank in used_cands:
            continue
        score = score_text_against_candidate(slot_ocrs[si], candidates[rank])
        if score >= PLANOGRAM_POSITIONAL_FALLBACK_MIN_SCORE or exact_row_match:
            slot_to_cand[si] = rank
            used_cands.add(rank)

    learned = 0
    output: list[dict] = []
    for si, slot in enumerate(slots):
        ci = slot_to_cand.get(si)
        if ci is None:
            continue
        candidate = candidates[ci]
        best = slot_best[si]
        ocr = slot_ocrs[si]
        text_score = score_text_against_candidate(ocr, candidate)
        conf = max(0.58, text_score, float(best.get("confidence") or 0) * 0.85)
        source = "planogram_slot_ocr" if text_score >= PLANOGRAM_SLOT_MIN_SCORE else "planogram_slot"
        label = label_from_candidate(candidate, conf, source, ocr)
        merged = _merge_record(_union_record_box(slot), label)

        if (
            scan_id
            and slot_images[si] is not None
            and conf >= PLANOGRAM_LEARN_MIN_CONFIDENCE
            and text_score >= PLANOGRAM_SLOT_MIN_SCORE
        ):
            try:
                emb = embed_pil_images([slot_images[si]])[0]
                if learn_sku(emb, label, scan_id=scan_id):
                    learned += 1
                    merged["recognition_source"] = "planogram_learned"
            except Exception:
                pass

        output.append(merged)

    if learned:
        print(f"Planogram slot learning: {learned} SKU(s) (scan={scan_id})")

    return output if output else records
