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


def _brand_in_text(text: str, candidate: dict) -> float:
    blob = _norm(text)
    if not blob:
        return 0.0
    brand = _norm(candidate.get("brand") or "")
    if not brand:
        return 0.0
    if brand in blob:
        return 1.0
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
    brand_score = _brand_in_text(text, candidate)
    if brand_score <= 0.0:
        return 0.0
    product_score = _token_overlap(candidate.get("product_name") or "", text)
    sub = _norm(candidate.get("sub_category") or "")
    kind_bonus = 0.12 if sub and _text_has_kind(text, sub) else 0.0
    return min(1.0, brand_score * 0.55 + product_score * 0.33 + kind_bonus)


def best_candidate_from_text(
    text: str,
    candidates: list[dict],
    min_score: float = PLANOGRAM_MATCH_MIN_SCORE,
) -> tuple[dict, float] | None:
    best: dict | None = None
    best_score = 0.0
    for row in candidates:
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
    from app.faiss_matcher import is_ready, match_embeddings_batch
    from app.recognizer import GPT_MAX_FALLBACKS, _unknown_label

    scan_context = scan_context or {}
    candidates: list[dict] = scan_context.get("planogram_candidates") or []
    if not records or not candidates:
        from app.recognizer import classify_records_v2
        return classify_records_v2(records, scan_id=scan_id, scan_category=scan_category, scan_context=scan_context)

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "planogram": 0, "none": 0, "gpt_calls": 0}

    pending: list[int] = []
    ocr_texts: list[str] = [""] * len(records)

    for index in range(len(records)):
        pack_text = read_packaging_text(images[index])
        ocr_texts[index] = pack_text

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

        pending.append(index)

    if pending and is_ready():
        pending_embeddings = embeddings[pending]
        matches = match_embeddings_batch(pending_embeddings, threshold=0.78)
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
        match = best_candidate_from_text(ocr_texts[index], candidates, min_score=0.32)
        if match:
            candidate, score = match
            classified[index] = _merge_record(
                records[index],
                label_from_candidate(candidate, score, "planogram_fallback", ocr_texts[index]),
            )
            stats["planogram"] += 1
        else:
            classified[index] = _merge_record(records[index], _unknown_label())
            stats["none"] += 1

    stats["gpt_calls"] = gpt_used
    stats["unknown_count"] = stats["none"]
    stats["planogram_mode"] = True
    stats["planogram_candidates"] = len(candidates)

    output = [{k: v for k, v in row.items() if k != "_index"} for row in classified if row]
    return output, stats
