"""Wakes the website every few minutes so scheduled report emails go out on time.

The website decides which schedules are due and sends them; this only knocks on the door.
The shared token lives in the `service_secrets` table, readable by the service role only.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

import requests

from app.catalog_sync import _headers, is_configured

INTERVAL_SEC = max(60, int(os.getenv("REPORT_CRON_INTERVAL_SEC", "900")))
APP_ORIGIN = os.getenv("AISLIX_APP_ORIGIN", "https://aislix.com").rstrip("/")
ENABLED = os.getenv("REPORT_CRON_ENABLED", "true").lower() in {"1", "true", "yes"}
USER_AGENT = "AislixReportTimer/1.0 (+https://aislix.com)"

_started = False
# Shown on /health so ops can see the timer without log access. Never holds the token.
STATUS: dict[str, object] = {
    "state": "not_started",
    "interval_sec": INTERVAL_SEC,
    "last_run_at": None,
    "last_result": None,
    "last_processed": None,
}


def _record(result: str, processed: int | None = None) -> None:
    STATUS["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATUS["last_result"] = result[:200]
    STATUS["last_processed"] = processed


def _cron_secret() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    response = requests.get(
        f"{base}/rest/v1/service_secrets?name=eq.report_cron&select=value",
        headers=_headers(),
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"secret lookup answered {response.status_code}")
    rows = response.json() or []
    return str(rows[0].get("value") or "") if rows else ""


def run_once() -> None:
    secret = _cron_secret()
    if not secret:
        _record("no report_cron secret")
        print("[report-cron] no report_cron secret; skipping", flush=True)
        return
    response = requests.post(
        f"{APP_ORIGIN}/api/cron/report-schedules",
        headers={"Authorization": f"Bearer {secret}", "User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=120,
        allow_redirects=False,
    )
    if response.status_code != 200:
        _record(f"website answered {response.status_code}")
        print(f"[report-cron] website answered {response.status_code}", flush=True)
        return
    try:
        processed = int((response.json() or {}).get("processed", 0))
    except ValueError:
        _record("website answered 200 without JSON")
        print("[report-cron] website answered 200 without JSON", flush=True)
        return
    _record("ok", processed)
    if processed:
        print(f"[report-cron] sent {processed} scheduled report(s)", flush=True)


def _loop() -> None:
    time.sleep(60)
    while True:
        try:
            run_once()
        except Exception as exc:  # keep the timer alive through network blips
            _record(f"run failed: {type(exc).__name__}: {exc}")
            print(f"[report-cron] run failed: {exc}", flush=True)
        time.sleep(INTERVAL_SEC)


def start_report_cron() -> None:
    global _started
    if _started:
        return
    if not ENABLED:
        STATUS["state"] = "disabled"
        return
    if not is_configured():
        STATUS["state"] = "not_configured"
        print("[report-cron] Supabase service settings missing; timer off", flush=True)
        return
    _started = True
    STATUS["state"] = "running"
    threading.Thread(target=_loop, name="report-cron", daemon=True).start()
    print(f"[report-cron] every {INTERVAL_SEC}s -> {APP_ORIGIN}", flush=True)
