"""Caller checks: Supabase user tokens for product routes, in-memory caps for anonymous routes."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import threading
import time
from collections import deque
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, Request

TOKEN_CACHE_SECONDS = 300
_token_cache: dict[str, tuple[float, str]] = {}
_token_lock = threading.Lock()
_stats = {"verified": 0, "rejected": 0, "missing": 0}

MSG_SIGN_IN = "Sign in to Aislix to use this feature."
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def auth_mode() -> str:
    """enforce = reject callers without a valid token; observe = verify and count only."""
    mode = os.getenv("BACKEND_AUTH_MODE", "enforce").strip().lower()
    return mode if mode in {"enforce", "observe", "off"} else "enforce"


def _supabase() -> tuple[str, str]:
    return (
        os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )


def auth_status() -> dict:
    base, key = _supabase()
    return {
        "mode": auth_mode() if base and key else "not_configured",
        "supabase_host": urlparse(base).hostname if base else None,
        **_stats,
    }


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token if token.count(".") == 2 else None


def verify_user_token(token: str) -> str | None:
    """Return the Supabase user id for a valid access token, else None."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _token_lock:
        hit = _token_cache.get(digest)
        if hit and hit[0] > now:
            return hit[1]
    base, key = _supabase()
    try:
        response = requests.get(
            f"{base}/auth/v1/user",
            headers={"apikey": key, "Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Sign-in check is unavailable. Try again.") from exc
    if response.status_code != 200:
        return None
    user_id = str((response.json() or {}).get("id") or "")
    if not user_id:
        return None
    with _token_lock:
        if len(_token_cache) > 5000:
            for k in [k for k, v in _token_cache.items() if v[0] <= now]:
                _token_cache.pop(k, None)
        _token_cache[digest] = (now + TOKEN_CACHE_SECONDS, user_id)
    return user_id


def require_user(request: Request) -> str | None:
    """FastAPI dependency for routes that spend AI credit or write data on a user's behalf."""
    base, key = _supabase()
    mode = auth_mode()
    if mode == "off" or not base or not key:
        return None
    token = _bearer(request)
    user_id = verify_user_token(token) if token else None
    if user_id:
        _stats["verified"] += 1
        return user_id
    _stats["missing" if not token else "rejected"] += 1
    if mode == "enforce":
        raise HTTPException(status_code=401, detail=MSG_SIGN_IN)
    print(f"auth observe: {'missing' if not token else 'invalid'} token on {request.url.path}")
    return None


ACCESS_CACHE_SECONDS = 120
_access_cache: dict[str, tuple[float, bool]] = {}


def _rest_rows(path: str) -> list[dict]:
    base, key = _supabase()
    try:
        response = requests.get(
            f"{base}/rest/v1/{path}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Access check is unavailable. Try again.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Access check is unavailable. Try again.")
    rows = response.json()
    return rows if isinstance(rows, list) else []


def user_can_access_scan(user_id: str, scan_id: str) -> bool:
    """True when the user is an active member of the organization that owns the scan."""
    if not _UUID.match(scan_id or "") or not _UUID.match(user_id or ""):
        return False
    cache_key = f"{user_id}:{scan_id}"
    now = time.time()
    with _token_lock:
        hit = _access_cache.get(cache_key)
        if hit and hit[0] > now:
            return hit[1]
    scans = _rest_rows(f"shelf_scans?id=eq.{scan_id}&select=org_id")
    org_id = str((scans[0] or {}).get("org_id") or "") if scans else ""
    allowed = bool(org_id) and bool(
        _rest_rows(
            f"organization_members?org_id=eq.{org_id}&user_id=eq.{user_id}&status=eq.active&select=user_id"
        )
    )
    with _token_lock:
        if len(_access_cache) > 5000:
            _access_cache.clear()
        _access_cache[cache_key] = (now + ACCESS_CACHE_SECONDS, allowed)
    return allowed


def require_scan_access(user_id: str | None, scan_id: str) -> None:
    """Scan jobs are readable and runnable only by members of the scan's organization."""
    base, key = _supabase()
    if auth_mode() != "enforce" or not base or not key:
        return
    if not user_id or not user_can_access_scan(user_id, str(scan_id)):
        raise HTTPException(status_code=404, detail="Scan job not found.")


_job_owners: dict[str, str] = {}


def remember_job_owner(job_id: str, user_id: str | None) -> None:
    if job_id and user_id:
        with _token_lock:
            if len(_job_owners) > 20000:
                _job_owners.clear()
            _job_owners[job_id] = user_id


def require_job_owner(job_id: str, user_id: str | None) -> None:
    if auth_mode() != "enforce":
        return
    with _token_lock:
        owner = _job_owners.get(job_id)
    if not user_id or owner != user_id:
        raise HTTPException(status_code=404, detail="Document job not found.")


def edge_ip(request: Request) -> str | None:
    """Client IP as seen by Railway's edge (last X-Forwarded-For hop; earlier hops are caller-controlled)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else None


class WindowLimiter:
    """Sliding-window counter per key (single replica, resets on restart)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            if len(self._hits) > 20000:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True


limiter = WindowLimiter()


def enforce_limits(request: Request, route: str, *, per_ip: int, global_limit: int, window_seconds: int) -> None:
    ip = edge_ip(request) or "unknown"
    if not limiter.allow(f"{route}:global", global_limit, window_seconds) or not limiter.allow(
        f"{route}:ip:{ip}", per_ip, window_seconds
    ):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


def _allowed_fetch_hosts() -> set[str]:
    hosts = {h.strip().lower() for h in os.getenv("BACKEND_FETCH_ALLOWED_HOSTS", "").split(",") if h.strip()}
    base, _ = _supabase()
    if base and urlparse(base).hostname:
        hosts.add(urlparse(base).hostname.lower())
    return hosts


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def assert_fetchable_url(url: str) -> None:
    """Only fetch caller URLs from our storage (Supabase) or allow-listed hosts; data: URLs are inline."""
    raw = (url or "").strip()
    if raw.startswith("data:"):
        return
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise ValueError("Image and document links must be https storage URLs.")
    if _is_ip_literal(host):
        raise ValueError("Image and document links must use a storage host name.")
    if host in _allowed_fetch_hosts() or host.endswith(".supabase.co"):
        return
    raise ValueError("Image and document links must come from Aislix storage.")
