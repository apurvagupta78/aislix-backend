"""Anonymous landing-page shelf scans and lead capture (LinkedIn ads funnel)."""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from app.catalog_sync import _headers, is_configured

BASE_DIR = Path(__file__).resolve().parent.parent
LANDING_BUCKET = os.getenv("LANDING_SCANS_BUCKET", "landing-scans")
DAILY_LIMIT = int(os.getenv("LANDING_SCAN_DAILY_LIMIT", "5"))
MAX_BYTES = int(os.getenv("LANDING_SCAN_MAX_BYTES", str(10 * 1024 * 1024)))
ENABLED = os.getenv("LANDING_SCAN_ENABLED", "true").lower() in {"1", "true", "yes"}

SAMPLE_IMAGES: dict[str, Path] = {
    "shampoo-a1z": BASE_DIR / "data" / "reference" / "shampoo_a1z.jpg",
    "lays-a1l": BASE_DIR / "data" / "reference" / "lays_rack_a1l.jpg",
    "toothpaste-a1l": BASE_DIR / "data" / "reference" / "toothpaste_a1l.jpg",
}

SAMPLE_PLANOGRAMS: dict[str, Path] = {
    "lays-a1l": BASE_DIR / "data" / "fixtures" / "planogram_lays_a1l.csv",
}

SAMPLE_DEFAULTS: dict[str, dict[str, str]] = {
    "shampoo-a1z": {
        "label": "Personal care shampoo shelf (sample)",
        "category": "Personal Care",
        "sub_category": "shampoo",
        "sub_category_label": "Shampoo",
        "location": "A-1-Z",
        "shelf_label": "A-1-Z",
    },
    "lays-a1l": {
        "label": "Lay's chip rack — Magic Masala, Tomato Tango, Cream & Onion",
        "category": "Packaged Food & Snacks",
        "sub_category": "chips",
        "sub_category_label": "Chips",
        "location": "A-1-L",
        "shelf_label": "A-1-L",
    },
    "toothpaste-a1l": {
        "label": "Oral care shelf — Colgate, Oral-B, Sensodyne, regional toothpaste brands",
        "category": "Personal Care",
        "sub_category": "toothpaste",
        "sub_category_label": "Toothpaste",
        "location": "A-1-L",
        "shelf_label": "A-1-L",
    },
}

DEFAULT_SAMPLE_ID = "toothpaste-a1l"

_rate_cache: dict[str, tuple[int, str]] = {}


def public_base_url_from_headers(
    headers: dict[str, str],
    *,
    fallback_scheme: str = "http",
    fallback_host: str = "localhost",
) -> str:
    """HTTPS-aware public URL behind Railway / reverse proxies."""
    forwarded_proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    scheme = forwarded_proto or fallback_scheme
    host = headers.get("x-forwarded-host") or headers.get("host") or fallback_host
    return f"{scheme}://{host}".rstrip("/")


def new_session_token() -> str:
    return uuid.uuid4().hex


def hash_ip(ip: str | None) -> str:
    salt = os.getenv("LANDING_IP_HASH_SALT", "aislix-landing")
    value = (ip or "unknown").strip()
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:32]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _supabase_base() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _count_scans_today(ip_hash: str) -> int:
    base = _supabase_base()
    if not base:
        return 0
    today = _today_utc()
    url = (
        f"{base}/rest/v1/landing_demo_sessions"
        f"?select=id&ip_hash=eq.{ip_hash}"
        f"&scan_status=eq.completed"
        f"&created_at=gte.{today}T00:00:00Z"
    )
    headers = _headers()
    headers["Prefer"] = "count=exact"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return 0
        content_range = response.headers.get("content-range", "")
        if "/" in content_range:
            total = content_range.split("/")[-1]
            if total.isdigit():
                return int(total)
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0
    except Exception as exc:
        print(f"landing rate-limit count skipped: {exc}")
        return 0


def check_rate_limit(ip_hash: str) -> tuple[bool, int, int]:
    """Return (allowed, used_today, daily_limit)."""
    today = _today_utc()
    cached_count, cached_day = _rate_cache.get(ip_hash, (0, today))
    if cached_day != today:
        cached_count = 0
    db_count = _count_scans_today(ip_hash) if is_configured() else 0
    used = max(cached_count, db_count)
    if used >= DAILY_LIMIT:
        return False, used, DAILY_LIMIT
    _rate_cache[ip_hash] = (used + 1, today)
    return True, used + 1, DAILY_LIMIT


def resolve_sample_image(sample_id: str) -> tuple[bytes, dict[str, str]]:
    path = SAMPLE_IMAGES.get(sample_id)
    if path is None or not path.exists():
        known = ", ".join(sorted(SAMPLE_IMAGES))
        raise ValueError(f"Unknown sample_id '{sample_id}'. Known samples: {known}")
    defaults = SAMPLE_DEFAULTS.get(sample_id, {})
    return path.read_bytes(), dict(defaults)


def slim_scan_result(full: dict[str, Any]) -> dict[str, Any]:
    """Persistable summary — omit multi-MB PDF/CSV payloads."""
    keep = (
        "scan_id",
        "metrics",
        "inventory",
        "products",
        "executive_summary",
        "summary_text",
        "planogram_compliance",
        "scan_context",
        "category",
        "shelf_label",
        "facings_debug",
        "annotated_image_width",
        "annotated_image_height",
        "original_image_width",
        "original_image_height",
    )
    out = {key: full.get(key) for key in keep if key in full}
    out["total_products"] = full.get("total_products") or (full.get("metrics") or {}).get("total_products")
    return out


def sanitize_landing_inventory(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Landing scans have no planogram — hide planogram-only compliance labels."""
    rows: list[dict[str, Any]] = []
    for item in inventory:
        row = dict(item)
        status = (row.get("compliance_status") or "").lower()
        if status == "needs_review" or row.get("counted_in_totals") is False:
            row["status_label"] = "Needs review"
        else:
            row["status_label"] = "Detected"
        row.pop("compliance_status", None)
        row.pop("compliance_interpretation", None)
        rows.append(row)
    return rows


def landing_scan_response(full: dict[str, Any], session_token: str, *, sample_id: str | None = None) -> dict[str, Any]:
    inventory = sanitize_landing_inventory(full.get("inventory") or [])
    return {
        "landing_session_id": session_token,
        "scan_id": full.get("scan_id"),
        "status": "completed",
        "scan_mode": "audit_only" if not sample_id else "sample_with_planogram",
        "has_planogram": bool(sample_id),
        "sample_id": sample_id,
        "metrics": full.get("metrics") or full.get("summary"),
        "inventory": inventory,
        "products": full.get("products") or [],
        "executive_summary": full.get("executive_summary") or full.get("summary_text"),
        "annotated_image_base64": full.get("annotated_image_base64"),
        "annotated_image_mime": full.get("annotated_image_mime", "image/jpeg"),
        "annotated_image_width": full.get("annotated_image_width"),
        "annotated_image_height": full.get("annotated_image_height"),
        "original_image_base64": full.get("original_image_base64"),
        "original_image_mime": full.get("original_image_mime", "image/jpeg"),
        "facings_debug": full.get("facings_debug"),
        "scan_context": full.get("scan_context"),
        "category": full.get("category"),
        "shelf_label": full.get("shelf_label"),
        "csv_base64": full.get("csv_base64"),
    }


def _insert_session(row: dict[str, Any]) -> dict[str, Any] | None:
    base = _supabase_base()
    if not base:
        return None
    url = f"{base}/rest/v1/landing_demo_sessions"
    headers = _headers()
    headers["Prefer"] = "return=representation"
    try:
        response = requests.post(url, headers=headers, json=row, timeout=20)
        response.raise_for_status()
        rows = response.json()
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception as exc:
        print(f"landing session insert skipped: {exc}")
        return None


def _patch_session(session_token: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    base = _supabase_base()
    if not base:
        return None
    url = f"{base}/rest/v1/landing_demo_sessions?session_token=eq.{session_token}"
    headers = _headers()
    headers["Prefer"] = "return=representation"
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        response = requests.patch(url, headers=headers, json=patch, timeout=20)
        response.raise_for_status()
        rows = response.json()
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception as exc:
        print(f"landing session patch skipped: {exc}")
        return None


def _fetch_session(session_token: str) -> dict[str, Any] | None:
    base = _supabase_base()
    if not base:
        return None
    url = f"{base}/rest/v1/landing_demo_sessions?session_token=eq.{session_token}&limit=1"
    try:
        response = requests.get(url, headers=_headers(), timeout=15)
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None
    except Exception as exc:
        print(f"landing session fetch skipped: {exc}")
        return None


def upload_scan_image(session_token: str, scan_id: str, data: bytes) -> str | None:
    base = _supabase_base()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not key:
        return None
    path = f"{session_token}/{scan_id}.jpg"
    url = f"{base}/storage/v1/object/{LANDING_BUCKET}/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",
    }
    try:
        response = requests.post(url, headers=headers, data=data, timeout=60)
        if response.status_code in {200, 201}:
            return path
        print(f"landing image upload failed: {response.status_code} {response.text[:200]}")
    except Exception as exc:
        print(f"landing image upload skipped: {exc}")
    return None


def _upsert_session(row: dict[str, Any]) -> dict[str, Any] | None:
    base = _supabase_base()
    if not base:
        return None
    url = f"{base}/rest/v1/landing_demo_sessions"
    headers = _headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    row = {**row, "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        response = requests.post(url, headers=headers, json=row, timeout=20)
        response.raise_for_status()
        rows = response.json()
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception as exc:
        print(f"landing session upsert skipped: {exc}")
        return None


def ensure_session(
    session_token: str | None,
    *,
    ip_hash: str | None = None,
    utm: dict[str, str | None] | None = None,
) -> str:
    """Return existing or newly created session token."""
    token = (session_token or "").strip() or new_session_token()
    if _fetch_session(token):
        return token
    utm = utm or {}
    _insert_session(
        {
            "session_token": token,
            "ip_hash": ip_hash,
            "utm_source": utm.get("utm_source"),
            "utm_medium": utm.get("utm_medium"),
            "utm_campaign": utm.get("utm_campaign"),
            "utm_content": utm.get("utm_content"),
            "utm_term": utm.get("utm_term"),
            "scan_status": "pending",
        }
    )
    return token


def create_pending_session(
    *,
    session_token: str | None = None,
    ip_hash: str,
    utm: dict[str, str | None],
    referrer: str | None,
    user_agent: str | None,
    sample_id: str | None = None,
) -> str:
    token = session_token or new_session_token()
    row = {
        "session_token": token,
        "ip_hash": ip_hash,
        "utm_source": utm.get("utm_source"),
        "utm_medium": utm.get("utm_medium"),
        "utm_campaign": utm.get("utm_campaign"),
        "utm_content": utm.get("utm_content"),
        "utm_term": utm.get("utm_term"),
        "referrer": referrer,
        "user_agent": (user_agent or "")[:512] or None,
        "sample_id": sample_id,
        "scan_status": "processing",
    }
    _insert_session(row)
    return token


def save_scan_success(
    session_token: str,
    *,
    scan_id: str,
    sample_id: str | None,
    image_storage_path: str | None,
    category: str | None,
    full_result: dict[str, Any],
) -> None:
    slim = slim_scan_result(full_result)
    _patch_session(
        session_token,
        {
            "scan_id": scan_id,
            "sample_id": sample_id,
            "image_storage_path": image_storage_path,
            "category": category or full_result.get("category"),
            "scan_status": "completed",
            "scan_error": None,
            "scan_result": slim,
        },
    )


def save_scan_failure(session_token: str, error: str) -> None:
    _patch_session(
        session_token,
        {
            "scan_status": "failed",
            "scan_error": error[:1000],
        },
    )


def capture_lead(
    session_token: str,
    *,
    email: str,
    name: str | None = None,
    company: str | None = None,
    phone: str | None = None,
    role: str | None = None,
    ip_hash: str | None = None,
    utm: dict[str, str | None] | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "session_token": session_token,
        "lead_email": email.strip().lower(),
        "lead_name": (name or "").strip() or None,
        "lead_company": (company or "").strip() or None,
        "lead_phone": (phone or "").strip() or None,
        "lead_role": (role or "").strip() or None,
        "lead_captured_at": now,
        "scan_status": "pending",
    }
    if ip_hash:
        row["ip_hash"] = ip_hash
    utm = utm or {}
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        if utm.get(key):
            row[key] = utm[key]
    patched = _patch_session(session_token, {k: v for k, v in row.items() if k != "session_token"})
    if patched:
        return patched
    return _upsert_session(row)


def mark_onboarding_email_sent(session_token: str) -> None:
    _patch_session(
        session_token,
        {"onboarding_email_sent_at": datetime.now(timezone.utc).isoformat()},
    )


def mark_converted(session_token: str, user_id: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()
    return _patch_session(
        session_token,
        {
            "converted_user_id": user_id,
            "signed_up_at": now,
            "signup_completed": True,
        },
    )


def get_session_public(session_token: str) -> dict[str, Any] | None:
    row = _fetch_session(session_token)
    if not row:
        return None
    result = row.get("scan_result") or {}
    if row.get("scan_status") != "completed":
        return {
            "landing_session_id": session_token,
            "status": row.get("scan_status"),
            "scan_error": row.get("scan_error"),
            "lead_captured": bool(row.get("lead_email")),
            "signed_up": bool(row.get("signup_completed")),
        }
    merged = landing_scan_response(result, session_token, sample_id=row.get("sample_id"))
    merged["status"] = "completed"
    merged["lead_captured"] = bool(row.get("lead_email"))
    merged["signed_up"] = bool(row.get("signup_completed"))
    return merged


def parse_utm(form: dict[str, Any]) -> dict[str, str | None]:
    keys = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
    out: dict[str, str | None] = {}
    for key in keys:
        val = form.get(key)
        if val is None or val == "":
            out[key] = None
        else:
            out[key] = str(val).strip()
    return out


def sample_preview_base64(sample_id: str) -> tuple[str, str] | None:
    try:
        data, _ = resolve_sample_image(sample_id)
    except ValueError:
        return None
    return base64.b64encode(data).decode("utf-8"), "image/jpeg"


def list_samples() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for sample_id, path in SAMPLE_IMAGES.items():
        if not path.exists():
            continue
        defaults = SAMPLE_DEFAULTS.get(sample_id, {})
        items.append(
            {
                "sample_id": sample_id,
                "label": defaults.get("label") or sample_id,
                "category": defaults.get("category"),
                "location": defaults.get("location"),
                "is_default": sample_id == DEFAULT_SAMPLE_ID,
            }
        )
    return items


def load_sample_planogram(sample_id: str) -> list[dict[str, Any]]:
    path = SAMPLE_PLANOGRAMS.get(sample_id)
    if path is None or not path.exists():
        return []
    from app.planogram_csv import parse_csv_text

    parsed = parse_csv_text(path.read_text(encoding="utf-8"))
    return [row["data"] for row in parsed.get("rows", []) if row.get("valid") and row.get("data")]


def landing_metadata(
    category: str | None,
    location: str | None,
    shelf_label: str | None,
    *,
    sample_id: str | None = None,
    sample_defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    defaults = sample_defaults or {}
    meta: dict[str, Any] = {"export_facings": True}
    cat = category or defaults.get("category")
    loc = location or defaults.get("location")
    label = shelf_label or defaults.get("shelf_label")
    if cat:
        meta["category"] = cat
    if loc:
        meta["location"] = loc
    if label:
        meta["shelf_label"] = label
    sub = defaults.get("sub_category")
    sub_label = defaults.get("sub_category_label")
    if sub:
        meta["sub_category"] = sub
    if sub_label:
        meta["sub_category_label"] = sub_label
    if sample_id:
        planogram_items = load_sample_planogram(sample_id)
        if planogram_items:
            meta["planogram_items"] = planogram_items
            meta["planogram_items_full"] = planogram_items
    return meta
