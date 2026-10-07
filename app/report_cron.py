"""Wakes the website every few minutes so scheduled report emails go out on time.

The website decides which schedules are due and sends them; this only knocks on the door.
The shared token lives in the `service_secrets` table, readable by the service role only.
"""

from __future__ import annotations

import os
import threading
import time

import requests

from app.catalog_sync import _headers, is_configured

INTERVAL_SEC = max(60, int(os.getenv("REPORT_CRON_INTERVAL_SEC", "900")))
APP_ORIGIN = os.getenv("AISLIX_APP_ORIGIN", "https://aislix.com").rstrip("/")
ENABLED = os.getenv("REPORT_CRON_ENABLED", "true").lower() in {"1", "true", "yes"}

_started = False


def _cron_secret() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    response = requests.get(
        f"{base}/rest/v1/service_secrets?name=eq.report_cron&select=value",
        headers=_headers(),
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json() or []
    return str(rows[0].get("value") or "") if rows else ""


def run_once() -> None:
    secret = _cron_secret()
    if not secret:
        print("[report-cron] no report_cron secret; skipping", flush=True)
        return
    response = requests.post(
        f"{APP_ORIGIN}/api/cron/report-schedules",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=120,
        allow_redirects=False,
    )
    if response.status_code != 200:
        print(f"[report-cron] website answered {response.status_code}", flush=True)
        return
    processed = (response.json() or {}).get("processed", 0)
    if processed:
        print(f"[report-cron] sent {processed} scheduled report(s)", flush=True)


def _loop() -> None:
    time.sleep(60)
    while True:
        try:
            run_once()
        except Exception as exc:  # keep the timer alive through network blips
            print(f"[report-cron] run failed: {exc}", flush=True)
        time.sleep(INTERVAL_SEC)


def start_report_cron() -> None:
    global _started
    if _started or not ENABLED or not is_configured():
        return
    _started = True
    threading.Thread(target=_loop, name="report-cron", daemon=True).start()
    print(f"[report-cron] every {INTERVAL_SEC}s -> {APP_ORIGIN}", flush=True)
