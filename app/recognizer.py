"""Product recognition v2: OCR first, GPT for ambiguous crops, strict FAISS last."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

from app.brand_dictionary import category_allows_brand, match_from_text, reconcile_label_with_text
from app.clip_embeddings import embed_pil_images
from app.faiss_matcher import is_ready, match_embeddings_batch
from app.learned_catalog import learn_sku, metadata_to_sku
from app.ocr_reader import classify_with_ocr, read_packaging_text
from app.scan_context import gpt_context_prompt

load_dotenv()

_client: OpenAI | None = None
GPT_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
GPT_MAX_FALLBACKS = int(os.getenv("GPT_MAX_FALLBACKS", "80"))
RECOGNITION_V2 = os.getenv("RECOGNITION_V2", "true").lower() in {"1", "true", "yes"}
FAISS_THRESHOLD = float(os.getenv("FAISS_SIMILARITY_THRESHOLD", "0.92"))
FAISS_THRESHOLD_CONTEXT = float(os.getenv("FAISS_SIMILARITY_THRESHOLD_CONTEXT", "0.88"))
FAISS_THRESHOLD_RETRY = float(os.getenv("FAISS_SIMILARITY_THRESHOLD_RETRY", "0.82"))
PROPAGATE_THRESHOLD = float(os.getenv("PROPAGATE_SIMILARITY_THRESHOLD", "0.90"))
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


def _should_learn(label: dict) -> bool:
    source = label.get("recognition_source")
    if source not in {"gpt", "ocr"}:
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
        best_sim = 0.0
        best_label: dict | None = None
        for ref_emb, ref_label in known:
            sim = _cosine_similarity(probe, ref_emb)
            if sim >= PROPAGATE_THRESHOLD and sim > best_sim:
                best_sim = sim
                best_label = ref_label

        if use_ocr and best_label and pack_text:
            ref_brand = (best_label.get("brand") or "").lower()
            text_l = pack_text.lower()
            if "lipton" in text_l and ref_brand == "tata":
                ocr_fix = match_from_text(pack_text)
                if ocr_fix and _is_valid_label(ocr_fix) and _accept_ocr_label(ocr_fix, scan_context):
                    row = _merge_label(records[index], ocr_fix)
                    row["_index"] = index
                    row["recognition_source"] = "ocr+propagate"
                    classified[index] = row
                    known.append((probe, row))
                    propagated += 1
                    continue
                still_unknown.append(index)
                continue
            if "tata" in text_l and ref_brand == "lipton" and "tea" in text_l:
                still_unknown.append(index)
                continue

        if best_label:
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


def classify_records_v2(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
    scan_context: dict | None = None,
) -> tuple[list[dict], dict]:
    """FAISS → retry → propagate → OCR → GPT → unknown (OCR/GPT only on hard crops)."""
    if not records:
        return [], {}

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "learned": 0, "propagate": 0, "none": 0}
    pending: list[int] = list(range(len(records)))
    learned_new = 0
    ocr_texts: list[str] = [""] * len(records)
    faiss_cutoff = _faiss_threshold(scan_context)

    def _apply_faiss(indices: list[int], threshold: float) -> list[int]:
        nonlocal learned_new
        if not indices or not is_ready():
            return indices
        matches = match_embeddings_batch(embeddings[indices], threshold=threshold)
        still: list[int] = []
        for local_idx, (match, score) in enumerate(matches):
            global_idx = indices[local_idx]
            if match and _accept_faiss_match(match, scan_category, scan_context=scan_context):
                merged = {**records[global_idx], **match}
                merged["confidence"] = float(match.get("confidence") or score)
                merged["_index"] = global_idx
                source = match.get("recognition_source") or "faiss"
                stats["learned" if source == "learned" else "faiss"] += 1
                classified[global_idx] = merged
            else:
                still.append(global_idx)
        return still

    pending = _apply_faiss(pending, faiss_cutoff)
    pending = _apply_faiss(pending, FAISS_THRESHOLD_RETRY)

    # Fast visual-only propagation — no OCR (seeds from FAISS spread to identical facings).
    for _ in range(3):
        if not pending:
            break
        pending, round_prop = _propagate_shelf_labels(
            records, classified, embeddings, images, pending,
            scan_context=scan_context, use_ocr=False,
        )
        stats["propagate"] += round_prop

    ocr_gpt_queue: list[int] = []
    for index in pending:
        pack_text = read_packaging_text(images[index])
        ocr_texts[index] = pack_text
        ocr_label = classify_with_ocr(images[index], raw_text=pack_text)
        if ocr_label and _is_valid_label(ocr_label) and _accept_ocr_label(ocr_label, scan_context):
            row = _merge_label(records[index], ocr_label)
            row["_index"] = index
            classified[index] = row
            stats["ocr"] += 1
            if _should_learn(ocr_label) and learn_sku(embeddings[index], ocr_label, scan_id=scan_id):
                learned_new += 1
            continue
        ocr_gpt_queue.append(index)

    gpt_cap = _smart_gpt_cap(len(ocr_gpt_queue))
    gpt_used = 0
    faiss_retry_queue: list[int] = []
    for index in ocr_gpt_queue:
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

    faiss_retry_queue = _apply_faiss(faiss_retry_queue, 0.78)

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
) -> list[dict]:
    if RECOGNITION_V2:
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
        return classified
    return classify_records_v1(records, scan_id=scan_id)
