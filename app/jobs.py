"""In-memory async scan jobs (single-replica Railway deployment)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def start_job(scan_id: str, runner: Callable[[], dict]) -> dict[str, str]:
    with _lock:
        existing = _jobs.get(scan_id)
        if existing and existing["status"] == "processing":
            return {"scan_id": scan_id, "status": "processing"}
        _jobs[scan_id] = {"status": "processing", "result": None, "error": None}

    def _run() -> None:
        try:
            result = runner()
            with _lock:
                _jobs[scan_id] = {"status": "completed", "result": result, "error": None}
        except Exception as exc:
            with _lock:
                _jobs[scan_id] = {"status": "failed", "result": None, "error": str(exc)}

    threading.Thread(target=_run, daemon=True).start()
    return {"scan_id": scan_id, "status": "processing"}


def get_job(scan_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(scan_id)
        if not job:
            return None
        payload: dict[str, Any] = {"scan_id": scan_id, "status": job["status"]}
        if job["status"] == "completed" and job["result"] is not None:
            payload["result"] = job["result"]
        if job["status"] == "failed" and job["error"]:
            payload["error"] = job["error"]
        return payload
