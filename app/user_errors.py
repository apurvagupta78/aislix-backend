"""Map internal failures to safe, user-facing error messages."""

from __future__ import annotations

import re
from typing import Any

# --- Public messages (safe to show in UI) ---

MSG_SCAN_FAILED = (
    "We couldn't analyze this shelf image right now. Please try again in a few minutes."
)
MSG_SERVICE_UNAVAILABLE = (
    "Our analysis service is temporarily unavailable. Please try again later."
)
MSG_TIMEOUT = (
    "Analysis took too long. Please try again with a clearer photo."
)
MSG_NO_PRODUCTS = (
    "No products detected in this shelf image. Try a clearer photo with products facing the camera."
)
MSG_SERVER_ERROR = (
    "Something went wrong. Please try again or contact support at hello@aislix.com."
)
MSG_SAMPLE_UNAVAILABLE = "This demo sample isn't available."
MSG_EXPORT_FAILED = "We couldn't generate export files right now. Please try again later."


_INTERNAL_MARKERS = re.compile(
    r"|".join(
        [
            r"openai",
            r"make\.com",
            r"\bmake\b",
            r"webhook",
            r"scenario",
            r"ratelimit",
            r"rate[\s_-]?limit",
            r"\b429\b",
            r"\b500\b",
            r"\b502\b",
            r"\b503\b",
            r"quota",
            r"credits?",
            r"billing",
            r"platform\.openai",
            r"api[_-]?key",
            r"traceback",
            r"exception",
            r"module\s+\d+",
            r"yolo",
            r"faiss",
            r"requests\.",
            r"httpx",
            r"connection(?:error| refused)?",
            r"timed?\s*out",
            r"timeout",
            r"json\.decode",
            r"not valid json",
            r"http\s+\d{3}",
            r"webhook url",
            r"accepted instead",
            r"inventory or facings",
            r"reasoning effort",
            r"max tokens",
        ]
    ),
    re.IGNORECASE,
)

_SAFE_EXACT = {
    "scan job not found.",
    "landing session not found.",
    "landing scans are temporarily disabled.",
    "empty file upload.",
    "scan_id is required.",
    "no image_urls provided.",
    "image_url is required.",
    "planogram_items is required.",
    "inventory is required.",
    "valid email is required.",
    "landing_session_id and user_id are required.",
    'missing "file" in multipart body.',
    'expected multipart file upload or json body with "image_urls".',
}

_SAFE_PREFIXES = (
    "missing ",
    "select a category",
    "select a sub-category",
    "no products detected",
    "daily demo scan limit reached",
    "image too large",
    "category is required",
    "store_id is required",
    "location is required",
    "sub_category is required",
    "sub_category_custom is required",
    "unknown category:",
    "expected multipart/form-data",
)


def _normalize_message(raw: str) -> str:
    return " ".join(str(raw or "").strip().split())


def _is_safe_public_message(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in _SAFE_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _SAFE_PREFIXES)


def _looks_internal(message: str) -> bool:
    return bool(_INTERNAL_MARKERS.search(message))


def _is_no_products_error(message: str) -> bool:
    lowered = _normalize_message(message).lower()
    if lowered.startswith("no products detected"):
        return True
    markers = (
        "empty products list",
        "no products visible",
        "no shelf image",
        "visual audit could not be completed",
        "could not be completed because no shelf image",
    )
    return any(marker in lowered for marker in markers)


def sanitize_error_message(raw: str, *, context: str = "scan") -> str:
    """Return a user-safe message; never expose vendor or infra details."""
    message = _normalize_message(raw)
    if not message:
        return MSG_SCAN_FAILED if context == "scan" else MSG_SERVER_ERROR

    lowered = message.lower()

    if _is_no_products_error(message):
        return MSG_NO_PRODUCTS

    if "unknown sample_id" in lowered or "known samples:" in lowered:
        return MSG_SAMPLE_UNAVAILABLE

    if _is_safe_public_message(message):
        return message

    if re.search(r"timed?\s*out|timeout", lowered):
        return MSG_TIMEOUT

    if re.search(
        r"openai|credits?|billing|quota|ratelimit|rate[\s_-]?limit|\b429\b|platform\.openai",
        lowered,
    ):
        if _is_no_products_error(message):
            return MSG_NO_PRODUCTS
        return MSG_SERVICE_UNAVAILABLE

    if _looks_internal(message):
        if context == "export":
            return MSG_EXPORT_FAILED
        if context == "server":
            return MSG_SERVER_ERROR
        return MSG_SCAN_FAILED

    # Unknown errors default to generic — do not leak raw exception text.
    if context == "export":
        return MSG_EXPORT_FAILED
    if context == "server":
        return MSG_SERVER_ERROR
    return MSG_SCAN_FAILED


def public_error_from_exception(exc: Exception, *, context: str = "scan") -> str:
    return sanitize_error_message(str(exc), context=context)


def public_http_detail(status_code: int, detail: Any, *, context: str = "scan") -> Any:
    """Sanitize HTTPException detail for API responses."""
    if status_code < 400:
        return detail
    if status_code == 500:
        return MSG_SERVER_ERROR
    if status_code == 429:
        if isinstance(detail, str) and "daily demo scan limit" in detail.lower():
            return detail
        return MSG_SERVICE_UNAVAILABLE
    if status_code == 503:
        if isinstance(detail, str) and _is_safe_public_message(detail):
            return detail
        return MSG_SERVICE_UNAVAILABLE
    if status_code in {400, 404, 413}:
        if isinstance(detail, str):
            return sanitize_error_message(detail, context=context)
        return detail
    if status_code in {422, 502}:
        if isinstance(detail, str):
            return sanitize_error_message(detail, context=context)
        if isinstance(detail, list):
            sanitized: list[Any] = []
            for item in detail:
                if isinstance(item, dict):
                    msg = item.get("msg") or item.get("message") or str(item)
                    sanitized.append({**item, "msg": sanitize_error_message(str(msg), context=context)})
                else:
                    sanitized.append(sanitize_error_message(str(item), context=context))
            return sanitized
        return detail
    if isinstance(detail, str):
        return sanitize_error_message(detail, context=context)
    return detail
