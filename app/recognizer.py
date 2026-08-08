"""Product recognition: FAISS catalog first, GPT Vision fallback."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

from app.faiss_matcher import is_ready, match_pil_image
from app.grouping import group_similar_products

load_dotenv()

_client: OpenAI | None = None
GPT_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")


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
            "brand": "",
            "product_name": "Unknown Product",
            "variant": "",
            "confidence": 0.0,
            "category": "General",
            "recognition_source": "gpt",
        }


def classify_group(representative: dict) -> dict:
    image = Image.open(representative["image_path"]).convert("RGB")
    if is_ready():
        try:
            match, _score = match_pil_image(image)
            if match:
                return match
        except Exception:
            pass
    return classify_with_gpt(image)


def _confidence_for_crop(item: dict, group_label: dict) -> float:
    image = Image.open(item["image_path"]).convert("RGB")
    if is_ready():
        try:
            match, score = match_pil_image(image, threshold=0.0)
            if match:
                return float(match.get("confidence") or score)
            return round(float(score), 4)
        except Exception:
            pass
    return float(group_label.get("confidence") or 0.0)


def classify_records(records: list[dict]) -> list[dict]:
    groups = group_similar_products(records)
    classified: list[dict] = []
    for group in groups:
        label = classify_group(group[0])
        for item in group:
            merged = {**item, **label}
            merged["confidence"] = _confidence_for_crop(item, label)
            classified.append(merged)
    return classified
