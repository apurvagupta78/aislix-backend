"""Product recognition v2: OCR first, GPT for ambiguous crops, strict FAISS last."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

from app.brand_dictionary import category_allows_brand
from app.clip_embeddings import embed_pil_images
from app.faiss_matcher import is_ready, match_embeddings_batch
from app.learned_catalog import learn_sku, metadata_to_sku
from app.ocr_reader import classify_with_ocr

load_dotenv()

_client: OpenAI | None = None
GPT_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
GPT_MAX_FALLBACKS = int(os.getenv("GPT_MAX_FALLBACKS", "80"))
RECOGNITION_V2 = os.getenv("RECOGNITION_V2", "true").lower() in {"1", "true", "yes"}
FAISS_THRESHOLD = float(os.getenv("FAISS_SIMILARITY_THRESHOLD", "0.92"))
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
- brand = manufacturer shown on pack (e.g. Lipton, Tetley, Mars)
- product_name = product type (e.g. Green Tea, Tea Bags, Chocolate Bar)
- variant = flavor/size if visible (e.g. 25 bags, 200g)
- confidence = 0.0 to 1.0 based on label readability
- Use "Unknown" / "Unidentified SKU" ONLY if the pack is unreadable

No markdown or extra text.
"""


def classify_with_gpt(image: Image.Image, ocr_hint: str = "") -> dict:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    hint = f"\nOCR hint (may be partial): {ocr_hint}" if ocr_hint else ""
    try:
        response = get_client().responses.create(
            model=GPT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": GPT_PROMPT + hint},
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
    dynamic = max(20, int(miss_count * 0.4))
    return min(GPT_MAX_FALLBACKS, dynamic)


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


def _accept_faiss_match(match: dict, scan_category: str | None) -> bool:
    brand = match.get("brand") or ""
    sku = match.get("sku") or ""
    return category_allows_brand(scan_category, brand, sku)


def classify_records_v2(
    records: list[dict],
    scan_id: str | None = None,
    scan_category: str | None = None,
) -> tuple[list[dict], dict]:
    """OCR → GPT → learned/base FAISS → unknown."""
    if not records:
        return [], {}

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    stats = {"ocr": 0, "gpt": 0, "faiss": 0, "learned": 0, "none": 0}
    gpt_queue: list[tuple[int, str]] = []
    faiss_queue: list[int] = []
    learned_new = 0

    for index, (record, image) in enumerate(zip(records, images)):
        ocr_label = classify_with_ocr(image)
        if ocr_label and _is_valid_label(ocr_label):
            classified[index] = _merge_label(record, ocr_label)
            stats["ocr"] += 1
            if _should_learn(ocr_label) and learn_sku(embeddings[index], ocr_label, scan_id=scan_id):
                learned_new += 1
            continue
        ocr_hint = (ocr_label or {}).get("visible_text", "") if ocr_label else ""
        gpt_queue.append((index, ocr_hint))

    gpt_cap = _smart_gpt_cap(len(gpt_queue))
    gpt_used = 0
    for index, ocr_hint in gpt_queue:
        if gpt_used < gpt_cap:
            label = classify_with_gpt(images[index], ocr_hint=ocr_hint)
            gpt_used += 1
            if _is_valid_label(label):
                classified[index] = _merge_label(records[index], label)
                stats["gpt"] += 1
                if _should_learn(label) and learn_sku(embeddings[index], label, scan_id=scan_id):
                    learned_new += 1
                continue
        faiss_queue.append(index)

    if faiss_queue and is_ready():
        sub_embeddings = embeddings[faiss_queue]
        matches = match_embeddings_batch(sub_embeddings, threshold=FAISS_THRESHOLD)
        still_unknown: list[int] = []
        for local_idx, (match, score) in enumerate(matches):
            global_idx = faiss_queue[local_idx]
            if match and _accept_faiss_match(match, scan_category):
                merged = {**records[global_idx], **match}
                merged["confidence"] = float(match.get("confidence") or score)
                source = match.get("recognition_source") or "faiss"
                stats["learned" if source == "learned" else "faiss"] += 1
                classified[global_idx] = merged
            else:
                still_unknown.append(global_idx)
        faiss_queue = still_unknown

    for index in faiss_queue:
        classified[index] = _merge_label(records[index], _unknown_label())
        stats["none"] += 1

    if learned_new:
        print(f"Learned {learned_new} new SKU(s) (scan={scan_id})")

    stats["gpt_calls"] = gpt_used
    stats["unknown_count"] = stats["none"]
    return [row for row in classified if row is not None], stats


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
) -> list[dict]:
    if RECOGNITION_V2:
        classified, stats = classify_records_v2(records, scan_id=scan_id, scan_category=scan_category)
        print(
            "Recognition v2:",
            f"ocr={stats.get('ocr', 0)}",
            f"gpt={stats.get('gpt', 0)}",
            f"faiss={stats.get('faiss', 0)}",
            f"learned={stats.get('learned', 0)}",
            f"unknown={stats.get('none', 0)}",
            f"gpt_calls={stats.get('gpt_calls', 0)}",
        )
        return classified
    return classify_records_v1(records, scan_id=scan_id)
