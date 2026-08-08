"""Product recognition: FAISS catalog first, GPT Vision fallback."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

from app.clip_embeddings import embed_pil_images
from app.faiss_matcher import is_ready, match_embeddings_batch

load_dotenv()

_client: OpenAI | None = None
GPT_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
GPT_MAX_FALLBACKS = int(os.getenv("GPT_MAX_FALLBACKS", "12"))


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        _client = OpenAI(api_key=api_key)
    return _client


GPT_PROMPT = """
Identify this retail product.

Return ONLY valid JSON in this format:
{
  "brand": "",
  "product_name": "",
  "variant": "",
  "confidence": 0.0
}

Do not include markdown or extra text.
"""


def classify_with_gpt(image: Image.Image) -> dict:
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    try:
        response = get_client().responses.create(
            model=GPT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": GPT_PROMPT},
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
        return result
    except Exception:
        return {
            "brand": "Unknown",
            "product_name": "Unidentified SKU",
            "variant": "",
            "confidence": 0.35,
            "category": "General",
            "recognition_source": "gpt",
        }


def _unknown_label(confidence: float = 0.35) -> dict:
    return {
        "brand": "Unknown",
        "product_name": "Unidentified SKU",
        "variant": "",
        "confidence": confidence,
        "category": "General",
        "recognition_source": "none",
    }


def classify_records(records: list[dict]) -> list[dict]:
    """Classify each detected crop individually for accurate SKU + qty aggregation."""
    if not records:
        return []

    images = [Image.open(record["image_path"]).convert("RGB") for record in records]
    embeddings = embed_pil_images(images)
    classified: list[dict | None] = [None] * len(records)
    gpt_queue: list[int] = []

    if is_ready():
        matches = match_embeddings_batch(embeddings)
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
    for index in gpt_queue:
        if gpt_used < GPT_MAX_FALLBACKS:
            label = classify_with_gpt(images[index])
            gpt_used += 1
        else:
            label = _unknown_label()
        merged = {**records[index], **label}
        merged["confidence"] = float(label.get("confidence") or 0.35)
        classified[index] = merged

    return [row for row in classified if row is not None]
