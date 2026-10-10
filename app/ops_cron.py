"""Runs the database's periodic work: recurring audit schedules, due/overdue reminders
and corrective-action SLA escalations (marks overdue, escalates to manager then admins).

The functions are idempotent (occurrence keys and reminder log dedupe), so a missed or
repeated tick is harmless.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

import requests

from app.catalog_sync import _headers, is_configured

INTERVAL_SEC = max(60, int(os.getenv("OPS_CRON_INTERVAL_SEC", "900")))
ENABLED = os.getenv("OPS_CRON_ENABLED", "true").lower() in {"1", "true", "yes"}

# Order matters: schedules create assignments that reminders then cover.
JOBS: tuple[tuple[str, dict[str, object]], ...] = (
    ("process_due_audit_schedules", {"p_limit": 100}),
    ("process_assignment_reminders", {"p_limit": 500}),
)

_started = False
STATUS: dict[str, object] = {
    "state": "not_started",
    "interval_sec": INTERVAL_SEC,
    "last_run_at": None,
    "last_result": None,
}


def _rpc(name: str, args: dict[str, object]) -> object:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    response = requests.post(f"{base}/rest/v1/rpc/{name}", headers=_headers(), json=args, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"{name} answered {response.status_code}: {response.text[:120]}")
    return response.json()


def run_once() -> None:
    results: dict[str, object] = {}
    for name, args in JOBS:
        try:
            results[name] = _rpc(name, args)
        except Exception as exc:  # one failing job must not block the next
            results[name] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            print(f"[ops-cron] {name} failed: {exc}", flush=True)
    STATUS["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATUS["last_result"] = results
    print(f"[ops-cron] {results}", flush=True)


def _loop() -> None:
    time.sleep(90)
    while True:
        try:
            run_once()
        except Exception as exc:
            STATUS["last_result"] = f"run failed: {type(exc).__name__}: {exc}"[:200]
            print(f"[ops-cron] run failed: {exc}", flush=True)
        time.sleep(INTERVAL_SEC)


def start_ops_cron() -> None:
    global _started
    if _started:
        return
    if not ENABLED:
        STATUS["state"] = "disabled"
        return
    if not is_configured():
        STATUS["state"] = "not_configured"
        print("[ops-cron] Supabase service settings missing; timer off", flush=True)
        return
    _started = True
    STATUS["state"] = "running"
    threading.Thread(target=_loop, name="ops-cron", daemon=True).start()
    print(f"[ops-cron] every {INTERVAL_SEC}s", flush=True)
