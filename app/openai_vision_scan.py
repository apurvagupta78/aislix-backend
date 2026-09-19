"""Direct OpenAI vision scan provider (replaces Make.com webhook)."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.make_scan import (
    build_scan_metadata_payload,
    parse_make_response,
    use_openai_provider,
)
from app.scan_post_process import finalize_make_scan

BASE_DIR = Path(__file__).resolve().parent.parent
# Direct OpenAI / Astra API prompt (not Make.com).
PROMPT_PATH = BASE_DIR / "docs" / "ASTRA_RETAIL_INTELLIGENCE_PROMPT.md"
METADATA_PLACEHOLDER = "{{metadata}}"
LEGACY_METADATA_PLACEHOLDER = "{{11.metadata}}"

_cached_prompt: str | None = None


class OpenAIVisionScanError(Exception):
    """OpenAI vision call or response parsing failed."""


def vision_model() -> str:
    return os.getenv("OPENAI_VISION_MODEL", "gpt-6-astra").strip() or "gpt-6-astra"


def vision_reasoning_effort() -> str:
    return os.getenv("OPENAI_VISION_REASONING_EFFORT", "low").strip().lower() or "low"


def vision_max_output_tokens() -> int:
    raw = os.getenv("OPENAI_VISION_MAX_TOKENS", "8192")
    try:
        return max(256, int(raw))
    except ValueError:
        return 8192


def vision_timeout_seconds() -> float:
    raw = os.getenv("OPENAI_VISION_TIMEOUT_SECONDS", "240")
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 240.0


def vision_max_image_px() -> int:
    raw = os.getenv("OPENAI_VISION_MAX_IMAGE_PX", "2048")
    try:
        return max(512, int(raw))
    except ValueError:
        return 2048


def vision_jpeg_quality() -> int:
    raw = os.getenv("OPENAI_VISION_JPEG_QUALITY", "85")
    try:
        return max(60, min(95, int(raw)))
    except ValueError:
        return 85


def vision_image_detail() -> str:
    detail = os.getenv("OPENAI_VISION_IMAGE_DETAIL", "auto").strip().lower()
    return detail if detail in {"low", "high", "auto"} else "auto"


def resolve_vision_image_detail(image: np.ndarray) -> str:
    """Use high detail only when the photo is large enough to benefit."""
    configured = vision_image_detail()
    if configured in {"low", "high"}:
        return configured
    h, w = image.shape[:2]
    threshold = int(os.getenv("OPENAI_VISION_HIGH_DETAIL_MIN_PX", "1024"))
    return "high" if max(h, w) > threshold else "auto"


def encode_vision_image_base64(image: np.ndarray) -> tuple[str, str]:
    from app.report_generator import encode_vision_image_bytes

    jpeg = encode_vision_image_bytes(
        image,
        max_long_edge=vision_max_image_px(),
        quality=vision_jpeg_quality(),
    )
    return base64.b64encode(jpeg).decode("ascii"), "image/jpeg"


def load_shelf_audit_prompt() -> str:
    global _cached_prompt
    if _cached_prompt is not None:
        return _cached_prompt
    if not PROMPT_PATH.is_file():
        raise OpenAIVisionScanError("Shelf audit prompt file is missing.")
    text = PROMPT_PATH.read_text(encoding="utf-8")
    marker = "Copy everything inside the code fence below"
    idx = text.find(marker)
    if idx >= 0:
        text = text[idx:]
    start = text.find("```")
    if start < 0:
        raise OpenAIVisionScanError("Shelf audit prompt not found.")
    start = text.find("\n", start) + 1
    end = text.find("```", start)
    if end < 0:
        raise OpenAIVisionScanError("Shelf audit prompt not found.")
    _cached_prompt = text[start:end].strip()
    return _cached_prompt


def build_vision_user_message(metadata: dict[str, Any]) -> str:
    from app.astra_vision import build_vision_prompt_text

    custom_prompt = (metadata.get("vision_prompt") or "").strip()
    if not custom_prompt:
        custom_prompt = build_vision_prompt_text(metadata)
    if custom_prompt:
        return custom_prompt

    prompt = load_shelf_audit_prompt()
    metadata_json = json.dumps(build_scan_metadata_payload(metadata), ensure_ascii=False)
    if METADATA_PLACEHOLDER in prompt:
        return prompt.replace(METADATA_PLACEHOLDER, metadata_json)
    if LEGACY_METADATA_PLACEHOLDER in prompt:
        return prompt.replace(LEGACY_METADATA_PLACEHOLDER, metadata_json)
    return f"{prompt}\n\nAudit context (JSON):\n{metadata_json}"


def call_openai_vision(
    *,
    scan_id: str,
    image: np.ndarray,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    from openai import APITimeoutError, OpenAIError

    from app.recognizer import get_client

    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise OpenAIVisionScanError("OPENAI_API_KEY is not configured.")

    image_b64, image_mime = encode_vision_image_base64(image)
    user_message = build_vision_user_message(metadata)
    image_part: dict[str, Any] = {
        "type": "input_image",
        "image_url": f"data:{image_mime};base64,{image_b64}",
    }
    detail = resolve_vision_image_detail(image)
    if detail:
        image_part["detail"] = detail

    request_kwargs: dict[str, Any] = {
        "model": vision_model(),
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_message},
                    image_part,
                ],
            }
        ],
        "max_output_tokens": vision_max_output_tokens(),
        "text": {"format": {"type": "json_object"}},
    }
    effort = vision_reasoning_effort()
    if effort and effort not in {"none", "off", "false", "0"}:
        request_kwargs["reasoning"] = {"effort": effort}

    timeout = vision_timeout_seconds()
    started = time.time()
    print(
        f"OpenAI vision scan {scan_id}: starting model={vision_model()} effort={effort or 'none'} "
        f"detail={detail} timeout={int(timeout)}s image={image.shape[1]}x{image.shape[0]}"
    )
    last_exc: Exception | None = None
    response = None
    for attempt in range(2):
        try:
            response = get_client().responses.create(**request_kwargs, timeout=timeout)
            last_exc = None
            break
        except APITimeoutError as exc:
            raise OpenAIVisionScanError(f"Vision scan timed out after {int(timeout)}s.") from exc
        except OpenAIError as exc:
            last_exc = exc
            msg = str(exc).lower()
            retryable = any(
                token in msg
                for token in ("timeout", "temporar", "overloaded", "rate limit", "429", "500", "502", "503", "504")
            )
            if attempt == 0 and retryable:
                print(f"OpenAI vision scan {scan_id}: retrying after transient error: {exc!r}")
                time.sleep(1.5)
                continue
            raise OpenAIVisionScanError(f"Vision scan request failed: {exc}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                print(f"OpenAI vision scan {scan_id}: retrying after unexpected error: {exc!r}")
                time.sleep(1.5)
                continue
            raise OpenAIVisionScanError(f"Vision scan request failed: {exc}") from exc
    if response is None:
        raise OpenAIVisionScanError(f"Vision scan request failed: {last_exc}")
    elapsed = int((time.time() - started) * 1000)
    print(
        f"OpenAI vision scan {scan_id}: model={vision_model()} effort={effort or 'none'} "
        f"detail={detail} ms={elapsed} image={image.shape[1]}x{image.shape[0]}"
    )

    output_text = (getattr(response, "output_text", None) or "").strip()
    if not output_text:
        raise OpenAIVisionScanError("Vision model returned an empty response.")
    try:
        return parse_make_response(output_text, metadata=metadata)
    except Exception as exc:
        raise OpenAIVisionScanError(f"Vision response was not valid JSON: {exc}") from exc


def _apply_openai_model_labels(result: dict[str, Any]) -> dict[str, Any]:
    model = vision_model()
    label = f"openai+{model}"
    result["model_version"] = label
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        metrics["recognition_mode"] = "openai"
        metrics["detection_mode"] = label
        metrics["gpt_vision_calls"] = int(metrics.get("gpt_vision_calls") or 0) + 1
    return result


def run_openai_vision_scan_from_image(
    image: np.ndarray,
    scan_id: str | None = None,
    metadata: dict | None = None,
    *,
    image_url: str | None = None,
) -> dict:
    import uuid

    from app.reference_scan_cache import enrich_reference_sample_metadata, lookup_reference_parsed

    started = time.time()
    scan_id = scan_id or uuid.uuid4().hex[:8]
    metadata = enrich_reference_sample_metadata(image, metadata or {}, image_url=image_url)

    from app.astra_vision import patch_parsed_for_astra_comparison

    parsed = lookup_reference_parsed(image, metadata, image_url=image_url)
    if parsed is None:
        parsed = call_openai_vision(scan_id=scan_id, image=image, metadata=metadata)
    parsed, astra_key, astra_block = patch_parsed_for_astra_comparison(parsed, metadata)
    processing_ms = int((time.time() - started) * 1000)
    result = finalize_make_scan(
        image,
        scan_id=scan_id,
        metadata=metadata,
        parsed=parsed,
        processing_ms=processing_ms,
    )
    if astra_key and astra_block:
        result[astra_key] = astra_block
    if parsed.get("reference_cache"):
        result["reference_cache"] = parsed["reference_cache"]
    return _apply_openai_model_labels(result)


__all__ = [
    "OpenAIVisionScanError",
    "build_vision_user_message",
    "call_openai_vision",
    "load_shelf_audit_prompt",
    "run_openai_vision_scan_from_image",
    "use_openai_provider",
    "vision_model",
]
