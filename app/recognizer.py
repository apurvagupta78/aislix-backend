"""Product recognition: v3 FAISS-first, v2 OCR-first, v1 legacy."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

from app.brand_dictionary import (
    category_allows_brand,
    label_conflicts_with_pack_text,
    label_conflicts_with_tea_pack,
    match_from_text,
    ocr_agrees_with_label,
    reconcile_label_with_text,
)
from app.clip_embeddings import embed_pil_images
from app.faiss_matcher import is_ready, match_embeddings_batch, match_embeddings_batch_topk
from app.learned_catalog import learn_sku, metadata_to_sku
from app.ocr_reader import classify_with_ocr, read_packaging_text
from app.scan_context import (
    gpt_context_prompt,
    product_type_matches_sub_category,
    propagation_type_conflict,
    strict_subcategory_gates_enabled,
    sub_category_blocks_brand,
)

load_dotenv()

_client: OpenAI | None = None
GPT_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
GPT_MAX_FALLBACKS = int(os.getenv("GPT_MAX_FALLBACKS", "80"))
RECOGNITION_V2 = os.getenv("RECOGNITION_V2", "true").lower() in {"1", "true", "yes"}
RECOGNITION_V3 = os.getenv("RECOGNITION_V3", "false").lower() in {"1", "true", "yes"}
FAISS_TIE_MARGIN = float(os.getenv("FAISS_TIE_MARGIN", "0.05"))
FAISS_THRESHOLD = float(os.getenv("FAISS_SIMILARITY_THRESHOLD", "0.92"))
FAISS_THRESHOLD_CONTEXT = float(os.getenv("FAISS_SIMILARITY_THRESHOLD_CONTEXT", "0.88"))
FAISS_THRESHOLD_RETRY = float(os.getenv("FAISS_SIMILARITY_THRESHOLD_RETRY", "0.82"))
FAISS_HIGH_CONFIDENCE = float(os.getenv("FAISS_HIGH_CONFIDENCE", "0.95"))
PROPAGATE_THRESHOLD = float(os.getenv("PROPAGATE_SIMILARITY_THRESHOLD", "0.90"))
PROPAGATE_THRESHOLD_NO_OCR = float(os.getenv("PROPAGATE_SIMILARITY_THRESHOLD_NO_OCR", "0.95"))
LEARN_MIN_CONFIDENCE = float(os.getenv("LEARN_MIN_CONFIDENCE", "0.7"))


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        _client = OpenAI(api_key=api_key)
    return _client


GPT_PROMPT = """
You are reading an Indian FMCG retail product from a shelf photo crop.

Read the visible brand name and product type printed on the packaging.
Ignore shelf price tags, stickers, and background text not on the product pack.

Return ONLY valid JSON:
{
  "brand": "",
  "product_name": "",
  "variant": "",
  "confidence": 0.0,
  "visible_text": ""
}

Rules:
- brand = manufacturer shown on pack (e.g. Lipton, Tetley, Tata Tea, Mars)
- product_name = product type or sub-brand (e.g. Green Tea, Tea Agni, Tea Bags)
- variant = flavor/size if visible (e.g. 25 bags, 200g)
- confidence = 0.0 to 1.0 based on label readability
- Read the logo on THIS pack only — do not guess from shelf neighbors
- Yellow Lipton boxes are Lipton, not Tata
- Tata Tea Agni pouches say "AGNI" — use brand Tata and product_name Tea Agni
- Use "Unknown" / "Unidentified SKU" ONLY if the pack is unreadable

No markdown or extra text.
"""


def classify_with_gpt(
    image: Image.Image,
    ocr_hint: str = "",
    scan_context: dict | None = None,
) -> dict:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    context_block = gpt_context_prompt(scan_context)
    hint = f"\nOCR hint (may be partial): {ocr_hint}" if ocr_hint else ""
    try:
        response = get_client().responses.create(
            model=GPT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": GPT_PROMPT + context_block + hint},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    ],
                }
            ],
        )
        result = json.loads(response.output_text)
        result["recognition_source"] = "gpt"
        result["category"] = result.get("category") or "General"
        result["confidence"] = float(result.get("confidence") or 0.75)
        if ocr_hint:
            result = reconcile_label_with_text(result, ocr_hint)
        if scan_context and not category_allows_brand(
            None,
            result.get("brand") or "",
            result.get("sku") or "",
            result.get("category") or "",
            scan_context=scan_context,
        ):
            return _unknown_label(confidence=0.4)
        if not result.get("sku"):
            result["sku"] = metadata_to_sku(
                result.get("brand") or "",
                result.get("product_name") or "",
                result.get("variant") or "",
            )
        return result
    except Exception:
        return _unknown_label()


def _unknown_label(confidence: float = 0.35) -> dict:
    return {
        "brand": "Unknown",
        "product_name": "Unidentified SKU",
        "variant": "",
        "confidence": confidence,
        "category": "General",
        "recognition_source": "none",
        "sku": "",
    }


def _is_valid_label(label: dict) -> bool:
    brand = (label.get("brand") or "").strip().lower()
    product = (label.get("product_name") or "").strip().lower()
    if brand in {"", "unknown", "n/a"}:
        return False
    if product in {"", "unknown", "unknown product", "unidentified sku", "n/a"}:
        return False
    return float(label.get("confidence") or 0) >= 0.5


def _is_ocr_source(source: str | None) -> bool:
    return bool(source and (source == "ocr" or source.startswith("ocr")))


def _should_learn(label: dict) -> bool:
    source = label.get("recognition_source")
    if source != "gpt" and not _is_ocr_source(source):
        return False
    if float(label.get("confidence") or 0) < LEARN_MIN_CONFIDENCE:
        return False
    return _is_valid_label(label)


def _smart_gpt_cap(miss_count: int) -> int:
    if miss_count <= 0:
        return 0
    return min(GPT_MAX_FALLBACKS, miss_count)


def _faiss_threshold(scan_context: dict | None) -> float:
    if scan_context and scan_context.get("aislix_category"):
        return FAISS_THRESHOLD_CONTEXT
    return FAISS_THRESHOLD


def _is_unknown_label(label: dict | None) -> bool:
    if not label:
        return True
    brand = (label.get("brand") or "").strip().lower()
    return brand in {"", "unknown"}


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _same_shelf_row(a: dict, b: dict) -> bool:
    """True when two facings sit on the same shelf row (similar vertical center)."""
    ay1, ay2 = float(a.get("y1", 0)), float(a.get("y2", 0))
    by1, by2 = float(b.get("y1", 0)), float(b.get("y2", 0))
    if ay2 <= ay1 or by2 <= by1:
        return True
    acy = (ay1 + ay2) / 2.0
    bcy = (by1 + by2) / 2.0
    row_tol = max(ay2 - ay1, by2 - by1) * 0.55
    return abs(acy - bcy) <= row_tol


def _same_shelf_column(a: dict, b: dict) -> bool:
    """True when two facings share the same bottle column (horizontal overlap)."""
    ax1, ax2 = float(a.get("x1", 0)), float(a.get("x2", 0))
    bx1, bx2 = float(b.get("x1", 0)), float(b.get("x2", 0))
    ix1, ix2 = max(ax1, bx1), min(ax2, bx2)
    if ix2 <= ix1:
        return False
    overlap = ix2 - ix1
    narrower = min(ax2 - ax1, bx2 - bx1)
    if narrower <= 0:
        return False
    if overlap / narrower >= 0.28:
        return True
    acx = (ax1 + ax2) / 2.0
    bcx = (bx1 + bx2) / 2.0
    return abs(acx - bcx) <= narrower * 0.38


def _propagation_neighbor_allowed(
    probe: dict,
    ref: dict,
    scan_context: dict | None,
) -> bool:
    if not _same_shelf_row(probe, ref):
        return False
    if (scan_context or {}).get("shelf_mode") in {"single_row", "single_bin"}:
        return _same_shelf_column(probe, ref)
    return True


def _try_ocr_override(
    records: list[dict],
    classified: list[dict | None],
    embeddings: np.ndarray,
    index: int,
    pack_text: str,
    scan_context: dict | None,
    known: list[tuple[np.ndarray, dict]],
) -> dict | None:
    ocr_fix = match_from_text(pack_text)
    if not ocr_fix or not _is_valid_label(ocr_fix) or not _accept_ocr_label(ocr_fix, scan_context):
        return None
    row = _merge_label(records[index], ocr_fix)
    row["_index"] = index
    row["recognition_source"] = "ocr+propagate"
    classified[index] = row
    known.append((embeddings[index], row))
    return row


def _propagate_shelf_labels(
    records: list[dict],
    classified: list[dict | None],
    embeddings: np.ndarray,
    images: list[Image.Image],
    unknown_indices: list[int],
    scan_context: dict | None = None,
    ocr_texts: list[str] | None = None,
    use_ocr: bool = False,
) -> tuple[list[int], int]:
    """Copy labels from identified facings to visually identical neighbors on the same shelf."""
    known: list[tuple[np.ndarray, dict]] = []
    for row in classified:
        if row and not _is_unknown_label(row):
            idx = row.get("_index")
            if idx is not None:
                known.append((embeddings[int(idx)], row))

    if not known:
        return unknown_indices, 0

    propagated = 0
    still_unknown: list[int] = []
    for index in unknown_indices:
        pack_text = (ocr_texts[index] if ocr_texts else "") or ""
        if use_ocr and not pack_text:
            pack_text = read_packaging_text(images[index])
            if ocr_texts is not None:
                ocr_texts[index] = pack_text

        if use_ocr and pack_text:
            ocr_match = match_from_text(pack_text)
            if ocr_match and _is_valid_label(ocr_match) and _accept_ocr_label(ocr_match, scan_context):
                row = _merge_label(records[index], ocr_match)
                row["_index"] = index
                row["recognition_source"] = "ocr+propagate"
                classified[index] = row
                known.append((embeddings[index], row))
                propagated += 1
                continue

        probe = embeddings[index]
        probe_record = records[index]
        best_sim = 0.0
        best_label: dict | None = None
        for ref_emb, ref_label in known:
            if not _propagation_neighbor_allowed(probe_record, ref_label, scan_context):
                continue
            sim = _cosine_similarity(probe, ref_emb)
            if sim >= PROPAGATE_THRESHOLD and sim > best_sim:
                best_sim = sim
                best_label = ref_label

        if use_ocr and best_label and pack_text:
            if label_conflicts_with_tea_pack(best_label, pack_text) or label_conflicts_with_pack_text(
                best_label, pack_text
            ):
                if _try_ocr_override(
                    records, classified, embeddings, index, pack_text, scan_context, known
                ):
                    propagated += 1
                    continue
                still_unknown.append(index)
                continue
            if not ocr_agrees_with_label(best_label, pack_text, strict=True):
                if _try_ocr_override(
                    records, classified, embeddings, index, pack_text, scan_context, known
                ):
                    propagated += 1
                    continue
                still_unknown.append(index)
                continue

        if best_label:
            if use_ocr and not pack_text.strip() and best_sim < PROPAGATE_THRESHOLD_NO_OCR:
                still_unknown.append(index)
                continue
            if use_ocr and pack_text and propagation_type_conflict(best_label, pack_text):
                if _try_ocr_override(
                    records, classified, embeddings, index, pack_text, scan_context, known
                ):
                    propagated += 1
                    continue
                still_unknown.append(index)
                continue
            label = {
                k: v
                for k, v in best_label.items()
                if k not in {"_index", "image_path", "bbox", "crop_path"}
            }
            if scan_context and not category_allows_brand(
                None,
                label.get("brand") or "",
                label.get("sku") or "",
                label.get("category") or "",
                scan_context=scan_context,
            ):
                still_unknown.append(index)
                continue
            if sub_category_blocks_brand(
                scan_context,
                label.get("brand") or "",
                pack_text,
                product_name=label.get("product_name") or "",
            ):
                still_unknown.append(index)
                continue
            label = {
                **label,
                "confidence": round(min(0.97, best_sim * 0.98), 4),
                "recognition_source": "propagate",
            }
            if use_ocr and pack_text:
                label = reconcile_label_with_text(label, pack_text)
                if scan_context and not category_allows_brand(
                    None,
                    label.get("brand") or "",
                    label.get("sku") or "",
                    label.get("category") or "",
                    scan_context=scan_context,
                ):
                    still_unknown.append(index)
                    continue
            classified[index] = _merge_label(records[index], label)
            classified[index]["_index"] = index
            known.append((probe, classified[index]))
            propagated += 1
        else:
            still_unknown.append(index)
    return still_unknown, propagated


def _merge_label(record: dict, label: dict) -> dict:
    merged = {**record, **label}
    merged["confidence"] = float(label.get("confidence") or 0.35)
    if not merged.get("sku"):
        merged["sku"] = metadata_to_sku(
            merged.get("brand") or "",
            merged.get("product_name") or "",
            merged.get("variant") or "",
        )
    return merged


def _accept_faiss_match(
    match: dict,
    scan_category: str | None,
    scan_context: dict | None = None,
) -> bool:
    brand = match.get("brand") or ""
    sku = match.get("sku") or ""
    entry_category = match.get("category") or ""
    return category_allows_brand(
        scan_category,
        brand,
        sku,
        entry_category=entry_category,
        scan_context=scan_context,
    )


def _accept_ocr_label(label: dict, scan_context: dict | None) -> bool:
    if not scan_context:
        return True
    return category_allows_brand(
        None,
        label.get("brand") or "",
        label.get("sku") or "",
        label.get("category") or "",
        scan_context=scan_context,
    )


def _accept_faiss_fusion(
    match: dict,
    score: float,
    ocr_text: str,
    scan_category: str | None,
    scan_context: dict | None = None,
) -> bool:
    """Accept FAISS only when aisle gates pass and OCR supports the match (or score is very high)."""
    if not _accept_faiss_match(match, scan_category, scan_context=scan_context):
        return False
    brand = match.get("brand") or ""
    if label_conflicts_with_tea_pack(match, ocr_text):
        return False
    if label_conflicts_with_pack_text(match, ocr_text):
        return False
    if sub_category_blocks_brand(
        scan_context,
        brand,
        ocr_text,
        product_name=match.get("product_name") or "",
    ):
        return False

    sub = (scan_context or {}).get("sub_category")
    if sub and sub != "others" and strict_subcategory_gates_enabled():
        if not product_type_matches_sub_category(sub, match, ocr_text):
            return False
        if ocr_text and len(ocr_text.strip()) >= 3 and not ocr_agrees_with_label(match, ocr_text):
            from app.scan_context import compatible_product_types, infer_product_type

            label_text = " ".join(
                [
                    match.get("brand") or "",
                    match.get("product_name") or "",
                    match.get("variant") or "",
                    match.get("sku") or "",
                ]
            )
            label_type = infer_product_type(label_text)
            if not label_type or (
                label_type != sub and not compatible_product_types(label_type, sub)
            ):
                return False
        return True

    if ocr_text and len(ocr_text.strip()) >= 3:
        if not ocr_agrees_with_label(match, ocr_text) and score < FAISS_HIGH_CONFIDENCE:
            return False
    return True


def recognition_v3_enabled() -> bool:
    return RECOGNITION_V3


def _brands_match(a: dict, b: dict) -> bool:
    from app.inventory import _normalize_brand_key

    ak = _normalize_brand_key(a.get("brand") or "")
    bk = _normalize_brand_key(b.get("brand") or "")
    return bool(ak and bk and ak == bk)


def _ocr_disambiguate(
    candidates: list[tuple[dict, float]],
    ocr_text: str,
    scan_category: str | None,
    scan_context: dict | None,
) -> dict | None:
    """Pick among FAISS top-K using OCR when scores are close or conflicting."""
    if not candidates:
        return None
    text_match = match_from_text(ocr_text) if ocr_text else None
    best_match: dict | None = None
    best_score = -1.0
    for match, score in candidates:
        if not _accept_faiss_match(match, scan_category, scan_context=scan_context):
            continue
        if ocr_text and (
            label_conflicts_with_tea_pack(match, ocr_text)
            or label_conflicts_with_pack_text(match, ocr_text)
        ):
            continue
        bonus = 0.0
        if ocr_text and ocr_agrees_with_label(match, ocr_text):
            bonus += 0.08
        if text_match and _brands_match(match, text_match):
            bonus += 0.15
        combined = score + bonus
        if combined > best_score:
            best_score = combined
            best_match = match
    if best_match is not None:
        result = dict(best_match)
        result["confidence"] = round(min(0.99, best_score), 4)
        result["recognition_source"] = "faiss+ocr"
        return result
    if text_match and _is_valid_label(text_match) and _accept_ocr_label(text_match, scan_context):
        text_match = dict(text_match)
        text_match["recognition_source"] = "ocr"
        return text_match
    return None


def _resolve_faiss_v3(
    candidates: list[tuple[dict, float]],
    ocr_text: str,
    scan_category: str | None,
    scan_context: dict | None,
    threshold: float | None = None,
) -> dict | None:
    """Accept FAISS top-1 or OCR-disambiguate when margin is tight or OCR conflicts."""
    from app.category_scope import filter_candidates_by_scope

    candidates = filter_candidates_by_scope(candidates, scan_context)
    if not candidates:
        return None
    faiss_cutoff = threshold if threshold is not None else _faiss_threshold(scan_context)
    match, score = candidates[0]
    second_score = candidates[1][1] if len(candidates) > 1 else 0.0
    margin = score - second_score

    if not _accept_faiss_match(match, scan_category, scan_context=scan_context):
        return _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context)

    if ocr_text and (
        label_conflicts_with_tea_pack(match, ocr_text)
        or label_conflicts_with_pack_text(match, ocr_text)
    ):
        dis = _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context)
        if dis:
            return dis
        text_match = match_from_text(ocr_text)
        if text_match and _is_valid_label(text_match) and _accept_ocr_label(text_match, scan_context):
            text_match = dict(text_match)
            text_match["recognition_source"] = "ocr"
            return text_match
        return None

    if sub_category_blocks_brand(
        scan_context,
        match.get("brand") or "",
        ocr_text,
        product_name=match.get("product_name") or "",
    ):
        return _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context)

    if score >= FAISS_HIGH_CONFIDENCE:
        result = dict(match)
        result["confidence"] = round(min(0.99, score), 4)
        result["recognition_source"] = match.get("recognition_source") or "faiss"
        return result

    if score >= faiss_cutoff:
        if margin >= FAISS_TIE_MARGIN:
            if not ocr_text or len(ocr_text.strip()) < 3 or ocr_agrees_with_label(match, ocr_text):
                result = dict(match)
                result["confidence"] = round(min(0.99, score), 4)
                result["recognition_source"] = match.get("recognition_source") or "faiss"
                return result
            return _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context)
        return _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context) or None

    if score >= FAISS_THRESHOLD_RETRY:
        return _ocr_disambiguate(candidates, ocr_text, scan_category, scan_context)

    return None


def _reconcile_conflicts_only(row: dict, pack_text: str) -> dict:
    """Adjust label only when pack OCR clearly conflicts with the assigned SKU."""
    if not pack_text or len(pack_text.strip()) < 3:
        return row
    if label_conflicts_with_tea_pack(row, pack_text) or label_conflicts_with_pack_text(row, pack_text):
        return reconcile_label_with_text(row, pack_text)
    if not ocr_agrees_with_label(row, pack_text, strict=True):
        text_match = match_from_text(pack_text)
        if text_match and _is_valid_label(text_match) and not _brands_match(row, text_match):
            return reconcile_label_with_text(row, pack_text)
    return row


def classify_records_v3(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict]:
    """FAISS primary → propagate → OCR tie-break → GPT → low FAISS → propagate → unknown."""
    if not records:
        return [], {}

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "learned": 0, "propagate": 0, "none": 0}
    learned_new = 0
    ocr_texts: list[str] = [read_packaging_text(img) for img in images]
    faiss_cutoff = _faiss_threshold(scan_context)

    def _count_source(label: dict) -> None:
        source = label.get("recognition_source") or "faiss"
        if source == "learned":
            stats["learned"] += 1
        elif source.startswith("ocr"):
            stats["ocr"] += 1
        else:
            stats["faiss"] += 1

    def _apply_faiss_v3(indices: list[int], threshold: float | None = None) -> list[int]:
        if not indices or not is_ready():
            return indices
        topk = match_embeddings_batch_topk(embeddings[indices], scan_context=scan_context)
        still: list[int] = []
        for local_idx, candidates in enumerate(topk):
            global_idx = indices[local_idx]
            resolved = _resolve_faiss_v3(
                candidates,
                ocr_texts[global_idx],
                scan_category,
                scan_context,
                threshold=threshold,
            )
            if resolved:
                merged = _merge_label(records[global_idx], resolved)
                merged["_index"] = global_idx
                _count_source(resolved)
                classified[global_idx] = merged
            else:
                still.append(global_idx)
        return still

    pending = list(range(len(records)))

    pending = _apply_faiss_v3(pending, faiss_cutoff)
    pending = _apply_faiss_v3(pending, FAISS_THRESHOLD_RETRY)

    for _ in range(2):
        if not pending:
            break
        pending, round_prop = _propagate_shelf_labels(
            records,
            classified,
            embeddings,
            images,
            pending,
            scan_context=scan_context,
            ocr_texts=ocr_texts,
            use_ocr=True,
        )
        stats["propagate"] += round_prop

    ocr_pending: list[int] = []
    for index in pending:
        pack_text = ocr_texts[index]
        ocr_label = classify_with_ocr(images[index], raw_text=pack_text)
        if not ocr_label or not _is_valid_label(ocr_label):
            ocr_label = match_from_text(pack_text)
        if ocr_label and _is_valid_label(ocr_label) and _accept_ocr_label(ocr_label, scan_context):
            if sub_category_blocks_brand(
                scan_context,
                ocr_label.get("brand") or "",
                pack_text,
                product_name=ocr_label.get("product_name") or "",
            ):
                ocr_pending.append(index)
                continue
            row = _merge_label(records[index], ocr_label)
            row["_index"] = index
            classified[index] = row
            stats["ocr"] += 1
            if _should_learn(ocr_label) and learn_sku(embeddings[index], ocr_label, scan_id=scan_id):
                learned_new += 1
            continue
        ocr_pending.append(index)

    pending = ocr_pending
    for _ in range(2):
        if not pending:
            break
        pending, round_prop = _propagate_shelf_labels(
            records,
            classified,
            embeddings,
            images,
            pending,
            scan_context=scan_context,
            ocr_texts=ocr_texts,
            use_ocr=True,
        )
        stats["propagate"] += round_prop

    gpt_cap = _smart_gpt_cap(len(pending))
    gpt_used = 0
    faiss_retry_queue: list[int] = []
    pending.sort(key=lambda idx: (0 if ocr_texts[idx].strip() else 1, idx))
    for index in pending:
        if gpt_used < gpt_cap:
            label = classify_with_gpt(
                images[index],
                ocr_hint=ocr_texts[index],
                scan_context=scan_context,
            )
            gpt_used += 1
            if _is_valid_label(label):
                row = _merge_label(records[index], label)
                row["_index"] = index
                classified[index] = row
                stats["gpt"] += 1
                if _should_learn(label) and learn_sku(embeddings[index], label, scan_id=scan_id):
                    learned_new += 1
                continue
        faiss_retry_queue.append(index)

    faiss_retry_queue = _apply_faiss_v3(faiss_retry_queue, 0.78)

    for _ in range(2):
        if not faiss_retry_queue:
            break
        faiss_retry_queue, propagated = _propagate_shelf_labels(
            records,
            classified,
            embeddings,
            images,
            faiss_retry_queue,
            scan_context=scan_context,
            ocr_texts=ocr_texts,
            use_ocr=True,
        )
        stats["propagate"] += propagated

    for index in faiss_retry_queue:
        if classified[index] is None:
            classified[index] = _merge_label(records[index], _unknown_label())
            stats["none"] += 1

    if learned_new:
        print(f"Learned {learned_new} new SKU(s) (scan={scan_id})")

    for index, row in enumerate(classified):
        if row:
            classified[index] = _reconcile_conflicts_only(row, ocr_texts[index])

    stats["gpt_calls"] = gpt_used
    stats["unknown_count"] = stats["none"]
    output: list[dict] = []
    for row in classified:
        if not row:
            continue
        cleaned = {k: v for k, v in row.items() if k != "_index"}
        output.append(cleaned)
    return output, stats


def classify_records_v2(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict]:
    """OCR → FAISS fusion → propagate → GPT → low FAISS → propagate → unknown."""
    if not records:
        return [], {}

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "learned": 0, "propagate": 0, "none": 0}
    learned_new = 0
    ocr_texts: list[str] = [""] * len(records)
    faiss_cutoff = _faiss_threshold(scan_context)

    def _apply_faiss_fusion(indices: list[int], threshold: float) -> list[int]:
        nonlocal learned_new
        if not indices or not is_ready():
            return indices
        matches = match_embeddings_batch(
            embeddings[indices], threshold=threshold, scan_context=scan_context
        )
        still: list[int] = []
        for local_idx, (match, score) in enumerate(matches):
            global_idx = indices[local_idx]
            ocr_text = ocr_texts[global_idx]
            if match and _accept_faiss_fusion(
                match, score, ocr_text, scan_category, scan_context=scan_context
            ):
                merged = {**records[global_idx], **match}
                merged["confidence"] = float(match.get("confidence") or score)
                merged["_index"] = global_idx
                if ocr_text:
                    merged = reconcile_label_with_text(merged, ocr_text)
                source = match.get("recognition_source") or "faiss"
                stats["learned" if source == "learned" else "faiss"] += 1
                classified[global_idx] = merged
            else:
                still.append(global_idx)
        return still

    # Step 1: OCR on every crop first.
    pending: list[int] = []
    for index in range(len(records)):
        pack_text = read_packaging_text(images[index])
        ocr_texts[index] = pack_text
        ocr_label = classify_with_ocr(images[index], raw_text=pack_text)
        if ocr_label and _is_valid_label(ocr_label) and _accept_ocr_label(ocr_label, scan_context):
            if sub_category_blocks_brand(
                scan_context,
                ocr_label.get("brand") or "",
                pack_text,
                product_name=ocr_label.get("product_name") or "",
            ):
                pending.append(index)
                continue
            row = _merge_label(records[index], ocr_label)
            row["_index"] = index
            classified[index] = row
            stats["ocr"] += 1
            if _should_learn(ocr_label) and learn_sku(embeddings[index], ocr_label, scan_id=scan_id):
                learned_new += 1
            continue
        pending.append(index)

    # Step 2: FAISS on OCR misses — must agree with OCR text or be very high confidence.
    pending = _apply_faiss_fusion(pending, faiss_cutoff)
    pending = _apply_faiss_fusion(pending, FAISS_THRESHOLD_RETRY)

    # Step 3: Propagate from OCR/FAISS-verified seeds only.
    for _ in range(2):
        if not pending:
            break
        pending, round_prop = _propagate_shelf_labels(
            records, classified, embeddings, images, pending,
            scan_context=scan_context, ocr_texts=ocr_texts, use_ocr=True,
        )
        stats["propagate"] += round_prop

    # Step 4: GPT on remaining hard crops (OCR-empty first).
    gpt_cap = _smart_gpt_cap(len(pending))
    gpt_used = 0
    faiss_retry_queue: list[int] = []
    pending.sort(key=lambda idx: (0 if ocr_texts[idx].strip() else 1, idx))
    for index in pending:
        if gpt_used < gpt_cap:
            label = classify_with_gpt(
                images[index],
                ocr_hint=ocr_texts[index],
                scan_context=scan_context,
            )
            gpt_used += 1
            if _is_valid_label(label):
                row = _merge_label(records[index], label)
                row["_index"] = index
                classified[index] = row
                stats["gpt"] += 1
                if _should_learn(label) and learn_sku(embeddings[index], label, scan_id=scan_id):
                    learned_new += 1
                continue
        faiss_retry_queue.append(index)

    # Step 5: Low-threshold FAISS with same OCR fusion gate.
    faiss_retry_queue = _apply_faiss_fusion(faiss_retry_queue, 0.78)

    for _ in range(2):
        if not faiss_retry_queue:
            break
        faiss_retry_queue, propagated = _propagate_shelf_labels(
            records, classified, embeddings, images, faiss_retry_queue,
            scan_context=scan_context, ocr_texts=ocr_texts, use_ocr=True,
        )
        stats["propagate"] += propagated

    for index in faiss_retry_queue:
        if classified[index] is None:
            classified[index] = _merge_label(records[index], _unknown_label())
            stats["none"] += 1

    if learned_new:
        print(f"Learned {learned_new} new SKU(s) (scan={scan_id})")

    # Final pass: OCR text always wins over FAISS/propagate/GPT when pack text is clear.
    for index, row in enumerate(classified):
        if not row:
            continue
        pack_text = ocr_texts[index]
        if pack_text and len(pack_text.strip()) >= 3:
            classified[index] = reconcile_label_with_text(row, pack_text)

    stats["gpt_calls"] = gpt_used
    stats["unknown_count"] = stats["none"]
    output: list[dict] = []
    for row in classified:
        if not row:
            continue
        cleaned = {k: v for k, v in row.items() if k != "_index"}
        output.append(cleaned)
    return output, stats


def classify_records_v1(records: list[dict], scan_id: str | None = None) -> list[dict]:
    """Legacy FAISS-first path."""
    if not records:
        return []

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    gpt_queue: list[int] = []
    learned_new = 0
    threshold = float(os.getenv("FAISS_SIMILARITY_THRESHOLD", "0.85"))

    if is_ready():
        matches = match_embeddings_batch(embeddings, threshold=threshold)
        for index, (item, (match, score)) in enumerate(zip(records, matches)):
            if match:
                merged = {**item, **match}
                merged["confidence"] = float(match.get("confidence") or score)
                classified[index] = merged
            else:
                gpt_queue.append(index)
    else:
        gpt_queue = list(range(len(records)))

    gpt_used = 0
    cap = int(os.getenv("GPT_MAX_FALLBACKS", "12"))
    for index in gpt_queue:
        if gpt_used < cap:
            label = classify_with_gpt(images[index])
            gpt_used += 1
            if _should_learn(label) and learn_sku(embeddings[index], label, scan_id=scan_id):
                learned_new += 1
        else:
            label = _unknown_label()
        merged = {**records[index], **label}
        merged["confidence"] = float(label.get("confidence") or 0.35)
        classified[index] = merged

    if learned_new:
        print(f"Learned {learned_new} new SKU(s) from GPT (scan={scan_id})")

    return [row for row in classified if row is not None]


def classify_records(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict]:
    if RECOGNITION_V3:
        if scan_context and scan_context.get("planogram_candidates"):
            from app.planogram_guided import classify_records_planogram_guided

            classified, stats = classify_records_planogram_guided(
                records,
                scan_id=scan_id,
                scan_category=scan_category,
                scan_context=scan_context,
            )
            print(
                "Recognition v3 planogram-guided:",
                f"planogram={stats.get('planogram', 0)}",
                f"faiss={stats.get('faiss', 0)}",
                f"ocr={stats.get('ocr', 0)}",
                f"gpt={stats.get('gpt', 0)}",
                f"unknown={stats.get('none', 0)}",
                f"candidates={stats.get('planogram_candidates', 0)}",
            )
            return classified, stats
        classified, stats = classify_records_v3(
            records,
            scan_id=scan_id,
            scan_category=scan_category,
            scan_context=scan_context,
        )
        print(
            "Recognition v3:",
            f"faiss={stats.get('faiss', 0)}",
            f"ocr={stats.get('ocr', 0)}",
            f"gpt={stats.get('gpt', 0)}",
            f"learned={stats.get('learned', 0)}",
            f"propagate={stats.get('propagate', 0)}",
            f"unknown={stats.get('none', 0)}",
            f"gpt_calls={stats.get('gpt_calls', 0)}",
        )
        return classified, stats
    if RECOGNITION_V2:
        if scan_context and scan_context.get("planogram_candidates"):
            from app.planogram_guided import classify_records_planogram_guided

            classified, stats = classify_records_planogram_guided(
                records,
                scan_id=scan_id,
                scan_category=scan_category,
                scan_context=scan_context,
            )
            print(
                "Recognition planogram-guided:",
                f"planogram={stats.get('planogram', 0)}",
                f"ocr={stats.get('ocr', 0)}",
                f"gpt={stats.get('gpt', 0)}",
                f"faiss={stats.get('faiss', 0)}",
                f"unknown={stats.get('none', 0)}",
                f"candidates={stats.get('planogram_candidates', 0)}",
            )
            return classified, stats
        classified, stats = classify_records_v2(
            records,
            scan_id=scan_id,
            scan_category=scan_category,
            scan_context=scan_context,
        )
        print(
            "Recognition v2:",
            f"ocr={stats.get('ocr', 0)}",
            f"gpt={stats.get('gpt', 0)}",
            f"faiss={stats.get('faiss', 0)}",
            f"learned={stats.get('learned', 0)}",
            f"propagate={stats.get('propagate', 0)}",
            f"unknown={stats.get('none', 0)}",
            f"gpt_calls={stats.get('gpt_calls', 0)}",
        )
        return classified, stats
    return classify_records_v1(records, scan_id=scan_id), {}
