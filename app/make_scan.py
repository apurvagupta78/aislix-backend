"""Make.com custom webhook scan provider."""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import numpy as np
import requests

from app.scan_post_process import finalize_make_scan

MAKE_PROVIDER = "make"


class MakeScanError(Exception):
    """Make.com webhook call or response parsing failed."""


def scan_provider() -> str:
    return os.getenv("SCAN_PROVIDER", "local").strip().lower()


def use_make_provider() -> bool:
    return scan_provider() == MAKE_PROVIDER


def make_fallback_local() -> bool:
    return os.getenv("MAKE_FALLBACK_LOCAL", "false").lower() in {"1", "true", "yes"}


def make_webhook_url() -> str:
    url = os.getenv("MAKE_SCAN_WEBHOOK_URL", "").strip()
    if not url:
        raise MakeScanError("MAKE_SCAN_WEBHOOK_URL is not configured.")
    return url


def make_timeout_seconds() -> int:
    raw = os.getenv("MAKE_SCAN_TIMEOUT_SECONDS", "90")
    try:
        return max(5, int(raw))
    except ValueError:
        return 90


def _webhook_headers(*, multipart: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if not multipart:
        headers["Content-Type"] = "application/json"
    secret = os.getenv("MAKE_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["X-Aislix-Secret"] = secret
    return headers


def make_upload_mode() -> str:
    return os.getenv("MAKE_UPLOAD_MODE", "multipart").strip().lower()


def encode_image_base64(image: np.ndarray) -> tuple[str, str]:
    from app.report_generator import encode_shelf_image_bytes

    jpeg = encode_shelf_image_bytes(image)
    return base64.b64encode(jpeg).decode("ascii"), "image/jpeg"


def build_make_multipart(
    scan_id: str,
    image: np.ndarray,
    metadata: dict[str, Any],
) -> tuple[dict[str, tuple[str, bytes, str]], dict[str, str]]:
    """Build multipart body matching Make Custom Webhook `image` file collection."""
    from app.report_generator import encode_shelf_image_bytes
    from app.scan_context import resolve_scan_context

    jpeg = encode_shelf_image_bytes(image)
    filename = os.getenv("MAKE_IMAGE_FILENAME", f"{scan_id}.jpg")
    field = os.getenv("MAKE_IMAGE_FIELD", "image")
    files = {field: (filename, jpeg, "image/jpeg")}

    scan_context = resolve_scan_context(metadata)
    audit_sub = scan_context.get("sub_category") or metadata.get("sub_category") or ""
    audit_label = (
        scan_context.get("sub_category_label")
        or metadata.get("sub_category_label")
        or audit_sub.replace("_", " ").title()
    )
    payload_metadata = {
        **metadata,
        "scan_context": {
            "aislix_category": scan_context.get("aislix_category"),
            "sub_category": audit_sub,
            "sub_category_label": audit_label,
            "shelf_label": scan_context.get("shelf_label") or metadata.get("shelf_label"),
            "location": scan_context.get("location") or metadata.get("location"),
        },
        "audit_instructions": (
            "Detect EVERY visible product on this shelf image — not only the audit sub-category. "
            "Include beverages (water bottles), mouthwash, snacks, cleaning products, and any other SKUs. "
            f"The user is auditing for '{audit_label}' but all products must appear in the JSON. "
            "For each product return: brand, product, variant, qty, confidence, shelf_position, "
            "product_category (e.g. toothpaste, water, mouthwash), and bbox_2d [x1,y1,x2,y2] "
            "normalized 0-1000 for annotated overlay on the shelf photo. "
            "Flag mismatches by setting product_category to the true category even when auditing another."
        ),
    }

    data: dict[str, str] = {
        "scan_id": scan_id,
        "metadata": json.dumps(payload_metadata),
    }
    if metadata.get("category") or scan_context.get("aislix_category"):
        data["category"] = str(metadata.get("category") or scan_context.get("aislix_category"))
    if audit_sub:
        data["sub_category"] = str(audit_sub)
    if audit_label:
        data["sub_category_label"] = str(audit_label)
    if metadata.get("shelf_label") or scan_context.get("shelf_label"):
        data["shelf_label"] = str(metadata.get("shelf_label") or scan_context.get("shelf_label"))
    return files, data


def build_make_json_payload(
    scan_id: str,
    image: np.ndarray,
    metadata: dict[str, Any],
    *,
    image_url: str | None = None,
) -> dict[str, Any]:
    image_b64, image_mime = encode_image_base64(image)
    payload: dict[str, Any] = {
        "scan_id": scan_id,
        "image_base64": image_b64,
        "image_mime": image_mime,
        "metadata": metadata,
    }
    if image_url:
        payload["image_url"] = image_url
    return payload


def _coerce_json_object(raw: Any) -> dict[str, Any]:
    """Accept dict, JSON string, or nested OpenAI Message.Content payloads."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MakeScanError("Make.com response was not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise MakeScanError("Make.com response must decode to a JSON object.")
    return raw


def _unwrap_make_body(raw: dict[str, Any]) -> dict[str, Any]:
    product_keys = {"inventory", "metrics", "facings", "executive_summary", "products", "Products"}

    for key in ("body", "data", "result", "response", "content", "message"):
        nested = raw.get(key)
        if isinstance(nested, dict) and product_keys.intersection(nested.keys()):
            return nested
        if isinstance(nested, str):
            try:
                parsed = json.loads(nested)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    return raw


def _map_make_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for row in rows:
        brand = (row.get("brand") or "Unknown").strip() or "Unknown"
        product_name = (
            row.get("product_name")
            or row.get("product")
            or row.get("name")
            or "Unknown"
        ).strip() or "Unknown"
        variant = (row.get("variant") or "").strip()
        qty = max(1, int(row.get("qty") or row.get("quantity") or row.get("facings") or 1))
        confidence = float(row.get("confidence") or 0.0)
        shelf_position = (row.get("shelf_position") or row.get("position") or row.get("shelf") or "").strip()
        product_category = (
            row.get("product_category")
            or row.get("category")
            or row.get("detected_category")
            or ""
        ).strip()
        pack_text = f"{brand} {product_name} {variant} {product_category}".strip()
        inventory.append(
            {
                "brand": brand,
                "product_name": product_name,
                "variant": variant,
                "quantity": qty,
                "facings": qty,
                "confidence": confidence,
                "shelf_position": shelf_position,
                "location": shelf_position,
                "product_category": product_category,
                "pack_text": pack_text,
                "counted_in_totals": True,
                "stock_status": "in_stock" if qty > 2 else "low_stock",
            }
        )
    return inventory


def _scale_coord(value: float, axis: int, *, normalized_1000: bool = False) -> int:
    if normalized_1000:
        return int(max(0, min(axis - 1, round(value / 1000.0 * axis))))
    if 0.0 <= value <= 1.0:
        return int(max(0, min(axis - 1, round(value * axis))))
    return int(max(0, min(axis - 1, round(value))))


def _parse_product_bbox(row: dict[str, Any], img_w: int, img_h: int) -> tuple[int, int, int, int] | None:
    """Parse bbox from OpenAI product row (pixels, 0-1, or 0-1000 normalized)."""
    coords: list[float] | None = None
    normalized_1000 = False

    bbox_2d = row.get("bbox_2d") or row.get("bounding_box_2d")
    if isinstance(bbox_2d, list) and len(bbox_2d) >= 4:
        coords = [float(bbox_2d[i]) for i in range(4)]
        normalized_1000 = max(coords) > 1.0
    else:
        bbox = row.get("bbox") or row.get("bounding_box") or row.get("box")
        if isinstance(bbox, dict):
            if all(bbox.get(k) is not None for k in ("x1", "y1", "x2", "y2")):
                coords = [float(bbox[k]) for k in ("x1", "y1", "x2", "y2")]
            elif all(bbox.get(k) is not None for k in ("left", "top", "right", "bottom")):
                coords = [
                    float(bbox["left"]),
                    float(bbox["top"]),
                    float(bbox["right"]),
                    float(bbox["bottom"]),
                ]
        elif all(row.get(k) is not None for k in ("x1", "y1", "x2", "y2")):
            coords = [float(row[k]) for k in ("x1", "y1", "x2", "y2")]

    if not coords:
        return None

    if max(coords) <= 1.0:
        x1 = _scale_coord(coords[0], img_w)
        y1 = _scale_coord(coords[1], img_h)
        x2 = _scale_coord(coords[2], img_w)
        y2 = _scale_coord(coords[3], img_h)
    else:
        normalized_1000 = normalized_1000 or max(coords) <= 1000.0
        x1 = _scale_coord(coords[0], img_w, normalized_1000=normalized_1000)
        y1 = _scale_coord(coords[1], img_h, normalized_1000=normalized_1000)
        x2 = _scale_coord(coords[2], img_w, normalized_1000=normalized_1000)
        y2 = _scale_coord(coords[3], img_h, normalized_1000=normalized_1000)

    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def build_facings_from_make_products(
    rows: list[dict[str, Any]],
    image_shape: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Turn OpenAI product rows with bbox into facings for annotated image rendering."""
    img_h, img_w = int(image_shape[0]), int(image_shape[1])
    facings: list[dict[str, Any]] = []
    for row in rows:
        bbox = _parse_product_bbox(row, img_w, img_h)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        brand = (row.get("brand") or "Product").strip() or "Product"
        product_name = (
            row.get("product_name") or row.get("product") or row.get("name") or "Detected"
        ).strip() or "Detected"
        variant = (row.get("variant") or "").strip()
        product_category = (
            row.get("product_category") or row.get("category") or row.get("detected_category") or ""
        ).strip()
        facings.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "brand": brand,
                "product_name": product_name,
                "variant": variant,
                "confidence": float(row.get("confidence") or 0.0),
                "pack_text": f"{brand} {product_name} {variant} {product_category}".strip(),
                "recognition_source": "make.com+openai_bbox",
            }
        )
    return facings


def _raw_product_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("products", "Products"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _products_from_make_data(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    for key in ("products", "Products", "inventory"):
        rows = data.get(key)
        if isinstance(rows, list) and rows:
            if key == "inventory" and rows[0].get("product_name"):
                return rows
            return _map_make_products(rows)
    return None


def parse_make_response(raw: Any) -> dict[str, Any]:
    """Normalize Make webhook JSON into a predictable internal shape."""
    data = _unwrap_make_body(_coerce_json_object(raw))

    inventory = _products_from_make_data(data)
    if inventory is None and isinstance(data.get("inventory"), list):
        inventory = data["inventory"]

    facings = data.get("facings") or data.get("classified") or data.get("products_detected")
    summary = data.get("executive_summary") or data.get("summary_text") or data.get("summary")
    annotated_image_base64 = (
        data.get("annotated_image_base64")
        or data.get("annotated_image")
        or data.get("overlay_image_base64")
    )

    is_full = (
        isinstance(inventory, list)
        and isinstance(data.get("metrics"), dict)
        and bool(summary or data.get("summary_text"))
    )

    return {
        "is_full": is_full,
        "raw": data,
        "inventory": inventory if isinstance(inventory, list) else None,
        "facings": facings if isinstance(facings, list) else None,
        "product_rows": _raw_product_rows(data),
        "annotated_image_base64": annotated_image_base64 if isinstance(annotated_image_base64, str) else None,
        "executive_summary": summary if isinstance(summary, str) else None,
    }


def call_make_webhook(
    *,
    scan_id: str,
    image: np.ndarray,
    metadata: dict[str, Any],
    image_url: str | None = None,
) -> dict[str, Any]:
    url = make_webhook_url()
    timeout = make_timeout_seconds()
    upload_mode = make_upload_mode()

    try:
        if upload_mode == "json":
            payload = build_make_json_payload(scan_id, image, metadata, image_url=image_url)
            response = requests.post(url, json=payload, headers=_webhook_headers(), timeout=timeout)
        else:
            files, data = build_make_multipart(scan_id, image, metadata)
            response = requests.post(
                url,
                files=files,
                data=data,
                headers=_webhook_headers(multipart=True),
                timeout=timeout,
            )
    except requests.Timeout as exc:
        raise MakeScanError(f"Make.com scan timed out after {timeout}s.") from exc
    except requests.RequestException as exc:
        raise MakeScanError(f"Make.com scan request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500] if response.text else response.reason
        raise MakeScanError(f"Make.com returned HTTP {response.status_code}: {detail}")

    try:
        body = response.json()
    except ValueError:
        body = response.text

    return parse_make_response(body)


def run_make_scan_from_image(
    image: np.ndarray,
    scan_id: str | None = None,
    metadata: dict | None = None,
    *,
    image_url: str | None = None,
) -> dict:
    import uuid

    started = time.time()
    scan_id = scan_id or uuid.uuid4().hex[:8]
    metadata = metadata or {}

    parsed = call_make_webhook(
        scan_id=scan_id,
        image=image,
        metadata=metadata,
        image_url=image_url,
    )
    processing_ms = int((time.time() - started) * 1000)
    return finalize_make_scan(
        image,
        scan_id=scan_id,
        metadata=metadata,
        parsed=parsed,
        processing_ms=processing_ms,
    )
