"""Anonymous landing-page shelf scans and lead capture (LinkedIn ads funnel)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from app.catalog_sync import _headers, is_configured

BASE_DIR = Path(__file__).resolve().parent.parent
LANDING_BUCKET = os.getenv("LANDING_SCANS_BUCKET", "landing-scans")
DAILY_LIMIT = int(os.getenv("LANDING_SCAN_DAILY_LIMIT", "5"))
DEMO_COOLDOWN_HOURS = int(os.getenv("LANDING_DEMO_COOLDOWN_HOURS", "24"))
MAX_BYTES = int(os.getenv("LANDING_SCAN_MAX_BYTES", str(10 * 1024 * 1024)))
ENABLED = os.getenv("LANDING_SCAN_ENABLED", "true").lower() in {"1", "true", "yes"}

SAMPLE_IMAGES: dict[str, Path] = {
    "shampoo-a1z": BASE_DIR / "data" / "reference" / "shampoo_a1z.jpg",
    "lays-a1l": BASE_DIR / "data" / "reference" / "lays_rack_a1l.jpg",
    "toothpaste-a1l": BASE_DIR / "data" / "reference" / "toothpaste_a1l.jpg",
}

SAMPLE_PLANOGRAMS: dict[str, Path] = {
    "lays-a1l": BASE_DIR / "data" / "fixtures" / "planogram_lays_a1l.csv",
    "toothpaste-a1l": BASE_DIR / "data" / "fixtures" / "planogram_toothpaste_a1l.csv",
}

SAMPLE_AUDIT_PACKAGES: dict[str, Path] = {
    "toothpaste-a1l": BASE_DIR / "data" / "demo" / "oral_care" / "audit_package.json",
}

LAYS_SHELF_BRAND_GUIDE = (
    "Lay's vertical chip rack (6 rows). Mandatory color → variant map: "
    "BLUE bags (rows 1–3, top) = India's Magic Masala — sum all blue row front facings (~18). "
    "RED bags (row 4, middle) = Tomato Tango or Spanish Tomato Tango — count red row only (~6). "
    "GREEN bags (rows 5–6, bottom) = American Style Cream & Onion — sum both green rows (~12). "
    "Do NOT label blue rows as Tomato Tango. Do NOT double-count shelf depth. "
    "Return separate products[] rows per variant with flavor in variant field when product is 'Potato Chips'."
)

TEA_SHELF_BRAND_GUIDE = (
    "Indian FMCG tea shelf. Read logos on pouches and cartons — do NOT return brand Unknown or "
    "product_name 'Tea' when pack text is readable. Expected SKUs: "
    "Brooke Bond Taaza = bright GREEN pouches (brand Brooke Bond or Tata Tea, product Taaza). "
    "Tata Tea Agni = BLUE or ORANGE/RED pouches with AGNI logo (brand Tata Tea, product Agni). "
    "Brooke Bond Red Label = RED pouches with gold/white accents. "
    "Brooke Bond Yellow Label = YELLOW pouches. "
    "Taj Mahal = premium Brooke Bond/Tata cartons. "
    "Lipton = green/yellow cartons and bags (Green Tea, Yellow Label, etc.). "
    "Tetley = brown/cream cartons. "
    "Return separate rows per flavor/size — never merge Taaza, Agni, Red Label into one generic Tea row. "
    "Snacks on tea bay (e.g. Britannia Little Hearts) → product_category packaged food, not tea. "
    "Ignore edge-cropped products on adjoining non-tea shelves unless clearly on the main tea bay."
)

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
        "shelf_brand_guide": LAYS_SHELF_BRAND_GUIDE,
    },
    "toothpaste-a1l": {
        "label": "Oral care shelf — Colgate, Oral-B, Odol, Doctor, Sensodyne, Closeup, Kolynos",
        "category": "Personal Care",
        "sub_category": "toothpaste",
        "sub_category_label": "Toothpaste",
        "location": "A-1-L",
        "shelf_label": "A-1-L",
        "shelf_brand_guide": (
            "Latin American / international toothpaste shelf. Expected brands: Colgate, Oral-B, "
            "Odol, Doctor, Sensodyne, Closeup, Kolynos. Red boxes may be Odol or Closeup — not "
            "Dabur Red. 'Doctor' is a regional toothpaste brand — never substitute Dabur. Do NOT "
            "output Dabur, Pepsodent, or Himalaya unless the brand name is clearly readable on "
            "packaging."
        ),
    },
}

DEFAULT_SAMPLE_ID = "toothpaste-a1l"

# Sub-category brand guides for homepage uploads (same hints as bundled reference samples).
SUB_CATEGORY_BRAND_GUIDES: dict[str, str] = {
    "toothpaste": SAMPLE_DEFAULTS["toothpaste-a1l"]["shelf_brand_guide"],
    "chips": LAYS_SHELF_BRAND_GUIDE,
    "tea": TEA_SHELF_BRAND_GUIDE,
}

def merge_landing_sample_defaults(
    *,
    sample_id: str | None,
    detected_sample_id: str | None,
    explicit_defaults: dict[str, str] | None = None,
    user_upload: bool = False,
) -> tuple[str | None, dict[str, str]]:
    """Merge explicit sample defaults with bundled reference sample metadata."""
    if user_upload:
        # Custom uploads must use only the category/sub-category the user selected.
        return None, dict(explicit_defaults or {})
    effective_id = sample_id or detected_sample_id
    merged: dict[str, str] = {}
    if effective_id:
        merged.update(SAMPLE_DEFAULTS.get(effective_id) or {})
    if explicit_defaults:
        merged.update(explicit_defaults)
    return effective_id, merged


def validate_landing_upload_context(
    *,
    category: str | None,
    sub_category: str | None,
) -> None:
    """Custom shelf uploads require explicit audit context from the user."""
    if not (category or "").strip():
        raise ValueError("Select a category before uploading your shelf photo.")
    if not (sub_category or "").strip():
        raise ValueError("Select a sub-category before uploading your shelf photo.")


def landing_skip_reference_cache(*, reference_sample_id: str | None) -> bool:
    """Known reference shelf photos use the same cached scan as dashboard for parity."""
    if reference_sample_id:
        return False
    return os.getenv("LANDING_SKIP_REFERENCE_CACHE", "true").lower() in {"1", "true", "yes"}


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


def _supabase_base() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _fetch_completed_sessions(ip_hash: str) -> list[dict[str, Any]]:
    """Completed demo audits for this IP hash, oldest first."""
    base = _supabase_base()
    if not base:
        return []
    url = (
        f"{base}/rest/v1/landing_demo_sessions"
        f"?select=id,updated_at,created_at"
        f"&ip_hash=eq.{ip_hash}"
        f"&scan_status=eq.completed"
        f"&order=updated_at.asc"
    )
    try:
        response = requests.get(url, headers=_headers(), timeout=15)
        if response.status_code != 200:
            return []
        rows = response.json()
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        print(f"landing completed-session fetch skipped: {exc}")
        return []


def get_demo_allowance(ip_hash: str) -> dict[str, Any]:
    """
    Authoritative demo allowance for an IP hash.

    Only successfully completed demo audits count. After the 5th completion,
    access returns exactly 24 hours after that completion timestamp.
    """
    limit = DAILY_LIMIT
    completed = _fetch_completed_sessions(ip_hash)
    now = datetime.now(timezone.utc)

    while len(completed) >= limit:
        fifth = completed[limit - 1]
        fifth_ts = _parse_ts(fifth.get("updated_at") or fifth.get("created_at"))
        if fifth_ts is None:
            break
        cooldown_end = fifth_ts + timedelta(hours=DEMO_COOLDOWN_HOURS)
        if now < cooldown_end:
            return {
                "used": limit,
                "limit": limit,
                "remaining": 0,
                "allowed": False,
                "next_available_at": cooldown_end.isoformat(),
            }
        window_start = cooldown_end
        completed = [
            row
            for row in completed
            if (_parse_ts(row.get("updated_at") or row.get("created_at")) or now) >= window_start
        ]

    used = len(completed)
    remaining = max(0, limit - used)
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "allowed": remaining > 0,
        "next_available_at": None,
    }


def demo_allowance_response(ip_hash: str) -> dict[str, Any]:
    """API-friendly allowance payload (backward compatible field names)."""
    allowance = get_demo_allowance(ip_hash)
    return {
        "demo_audits_used": allowance["used"],
        "demo_audits_limit": allowance["limit"],
        "demo_audits_remaining": allowance["remaining"],
        "demo_next_available_at": allowance.get("next_available_at"),
        "scans_used_today": allowance["used"],
        "scans_daily_limit": allowance["limit"],
    }


def check_rate_limit(ip_hash: str) -> tuple[bool, int, int]:
    """Return (allowed, used, limit) — only completed audits count."""
    allowance = get_demo_allowance(ip_hash)
    return allowance["allowed"], allowance["used"], allowance["limit"]


def resolve_sample_image(sample_id: str) -> tuple[bytes, dict[str, str]]:
    path = SAMPLE_IMAGES.get(sample_id)
    if path is None or not path.exists():
        known = ", ".join(sorted(SAMPLE_IMAGES))
        raise ValueError(f"Unknown sample_id '{sample_id}'. Known samples: {known}")
    defaults = SAMPLE_DEFAULTS.get(sample_id, {})
    return path.read_bytes(), dict(defaults)


def slim_share_snapshot(full: dict[str, Any]) -> dict[str, Any]:
    """Landing demo share payload — omit multi-MB image/CSV blobs."""
    omit = {"annotated_image_base64", "original_image_base64", "csv_base64"}
    return {key: value for key, value in full.items() if key not in omit}


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


def merge_landing_vision_metadata(
    metadata: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply optional Astra vision fields from landing scan form/JSON payloads."""
    out = dict(metadata)
    for key in ("vision_prompt", "analysis_mode", "operating_model", "focus_brand", "customer_type"):
        value = payload.get(key)
        if value is None:
            continue
        if hasattr(value, "read"):
            continue
        text = str(value).strip()
        if text:
            out[key] = text

    planogram_items = payload.get("planogram_items")
    if isinstance(planogram_items, str) and planogram_items.strip():
        try:
            parsed = json.loads(planogram_items)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and parsed:
            out["planogram_items"] = parsed
            out["planogram_items_full"] = parsed
    elif isinstance(planogram_items, list) and planogram_items:
        out["planogram_items"] = planogram_items
        out["planogram_items_full"] = planogram_items

    audit_package = payload.get("audit_package")
    if isinstance(audit_package, str) and audit_package.strip():
        try:
            parsed_pkg = json.loads(audit_package)
        except json.JSONDecodeError:
            parsed_pkg = None
        if isinstance(parsed_pkg, dict):
            out["audit_package"] = parsed_pkg
    elif isinstance(audit_package, dict):
        out["audit_package"] = audit_package

    return out


def landing_scan_response(
    full: dict[str, Any],
    session_token: str,
    *,
    sample_id: str | None = None,
    scanned_at: str | None = None,
) -> dict[str, Any]:
    inventory = sanitize_landing_inventory(full.get("inventory") or [])
    metrics = full.get("metrics") or full.get("summary") or {}
    return {
        "landing_session_id": session_token,
        "scan_id": full.get("scan_id"),
        "scanned_at": scanned_at or datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "scan_mode": "audit_only" if not sample_id else "sample_with_planogram",
        "has_planogram": bool(sample_id),
        "sample_id": sample_id,
        "analysis_mode": full.get("analysis_mode") or metrics.get("analysis_mode"),
        "metrics": metrics,
        "inventory": inventory,
        "products": full.get("products") or [],
        "brand_share": full.get("brand_share") or [],
        "top_brands": full.get("top_brands") or (full.get("brand_share") or [])[:10],
        "brand_share_all": full.get("brand_share_all") or [],
        "brand_share_scope": full.get("brand_share_scope") or metrics.get("brand_share_scope"),
        "brand_share_denominator": full.get("brand_share_denominator")
        or metrics.get("brand_share_denominator"),
        "compliance_alerts": full.get("compliance_alerts") or [],
        "subcategory_mismatches": full.get("subcategory_mismatches") or [],
        "recommendations": full.get("recommendations") or [],
        "alerts": full.get("alerts") or [],
        "executive_summary": full.get("executive_summary") or full.get("summary_text"),
        "role_summaries": full.get("role_summaries"),
        "retail_intelligence": full.get("retail_intelligence"),
        "astra_planogram_analysis": full.get("astra_planogram_analysis") or metrics.get("astra_planogram_analysis"),
        "astra_shelf_analysis": full.get("astra_shelf_analysis") or metrics.get("astra_shelf_analysis"),
        "visible_prices": full.get("visible_prices") or [],
        "visible_promotions": full.get("visible_promotions") or [],
        "shelf_issues": full.get("shelf_issues") or [],
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


def persist_share_session(session_token: str, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Upsert a completed demo audit so /share/:token and /landing/session/:token resolve it."""
    token = (session_token or "").strip()
    if not token:
        raise ValueError("Missing session token.")
    slim = slim_share_snapshot(snapshot)
    scan_id = str(snapshot.get("scan_id") or slim.get("scan_id") or "demo")
    patch = {
        "scan_id": scan_id,
        "scan_status": "completed",
        "scan_error": None,
        "scan_result": slim,
        "sample_id": snapshot.get("sample_id"),
        "category": snapshot.get("category") or snapshot.get("scan_category"),
    }
    patched = _patch_session(token, patch)
    if patched:
        return patched
    return _upsert_session(
        {
            "session_token": token,
            **patch,
        }
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
    scanned_at = row.get("updated_at") or row.get("created_at")
    merged = landing_scan_response(
        result,
        session_token,
        sample_id=row.get("sample_id"),
        scanned_at=scanned_at,
    )
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


def load_sample_audit_package(sample_id: str) -> dict[str, Any]:
    path = SAMPLE_AUDIT_PACKAGES.get(sample_id)
    if path is None or not path.exists():
        return {}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def landing_metadata(
    category: str | None,
    location: str | None,
    shelf_label: str | None,
    *,
    sample_id: str | None = None,
    sample_defaults: dict[str, str] | None = None,
    sub_category: str | None = None,
    sub_category_label: str | None = None,
    detected_sample_id: str | None = None,
    user_upload: bool = False,
) -> dict[str, Any]:
    effective_sample_id, defaults = merge_landing_sample_defaults(
        sample_id=sample_id,
        detected_sample_id=detected_sample_id,
        explicit_defaults=sample_defaults,
        user_upload=user_upload,
    )
    meta: dict[str, Any] = {"export_facings": True}
    if user_upload:
        meta["user_upload"] = True
    cat = category or defaults.get("category")
    loc = location or defaults.get("location")
    label = shelf_label or defaults.get("shelf_label")
    if cat:
        meta["category"] = cat
    if loc:
        meta["location"] = loc
    if label:
        meta["shelf_label"] = label
    elif loc:
        meta["shelf_label"] = loc
    sub = sub_category or defaults.get("sub_category")
    sub_label = sub_category_label or defaults.get("sub_category_label")
    if sub:
        meta["sub_category"] = sub
    if sub_label:
        meta["sub_category_label"] = sub_label
    elif sub:
        meta["sub_category_label"] = sub.replace("_", " ").title()
    # Homepage uploads often send category only — default beverage sub-category for Make context.
    if not meta.get("sub_category") and (meta.get("category") or "").strip().lower() == "beverages":
        meta["sub_category"] = "soft_drinks"
        meta["sub_category_label"] = "Soft drinks"
    if effective_sample_id:
        meta["sample_id"] = effective_sample_id
        planogram_items = load_sample_planogram(effective_sample_id)
        if planogram_items:
            meta["planogram_items"] = planogram_items
            meta["planogram_items_full"] = planogram_items
        audit_pkg = load_sample_audit_package(effective_sample_id)
        if audit_pkg:
            meta["audit_package"] = audit_pkg
            meta["demo_planogram"] = True
    elif user_upload and detected_sample_id:
        meta["reference_sample_id"] = detected_sample_id
        planogram_items = load_sample_planogram(detected_sample_id)
        if planogram_items:
            meta["planogram_items"] = planogram_items
            meta["planogram_items_full"] = planogram_items
        audit_pkg = load_sample_audit_package(detected_sample_id)
        if audit_pkg:
            meta["audit_package"] = audit_pkg
            meta["demo_planogram"] = True
    ref_for_cache = effective_sample_id or (detected_sample_id if user_upload else None)
    if landing_skip_reference_cache(reference_sample_id=ref_for_cache):
        meta["skip_reference_cache"] = True
    guide = defaults.get("shelf_brand_guide")
    if not guide:
        sub_key = (meta.get("sub_category") or "").strip().lower()
        guide = SUB_CATEGORY_BRAND_GUIDES.get(sub_key)
    if guide:
        meta["shelf_brand_guide"] = guide
    return meta
