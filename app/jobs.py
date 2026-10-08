"""In-memory async scan jobs (single-replica Railway deployment)."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from typing import Any

_lock = __import__("threading").Lock()
_jobs: dict[str, dict[str, Any]] = {}

# Anonymous demo jobs carry full results (images included); drop them once stale.
LANDING_JOB_PREFIX = "landing:"
LANDING_JOB_TTL_SECONDS = 3600


def _prune_landing_jobs() -> None:
    cutoff = time.time() - LANDING_JOB_TTL_SECONDS
    for job_id in [
        jid
        for jid, job in _jobs.items()
        if jid.startswith(LANDING_JOB_PREFIX) and job.get("finished_at", time.time()) < cutoff
    ]:
        del _jobs[job_id]


def _classify_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "vision_timeout"
    if "not valid json" in text or "jsondecode" in text:
        return "vision_invalid_json"
    if "no products" in text or "empty products" in text:
        return "no_products"
    if "openai" in text or "rate limit" in text or "429" in text:
        return "openai_upstream"
    if "image" in text and ("url" in text or "download" in text or "http" in text):
        return "image_fetch_failed"
    if "make.com" in text or "inventory or facings" in text:
        return "vision_missing_products"
    return "pipeline_exception"


def start_job(scan_id: str, runner: Callable[[], dict]) -> dict[str, str]:
    with _lock:
        _prune_landing_jobs()
        existing = _jobs.get(scan_id)
        if existing and existing["status"] == "processing":
            return {"scan_id": scan_id, "status": "processing"}
        _jobs[scan_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "error_code": None,
            "error_detail": None,
        }

    def _run() -> None:
        try:
            result = runner()
            with _lock:
                _jobs[scan_id] = {
                    "status": "completed",
                    "result": result,
                    "error": None,
                    "error_code": None,
                    "error_detail": None,
                    "finished_at": time.time(),
                }
        except Exception as exc:
            from app.user_errors import public_error_from_exception

            tb = traceback.format_exc()
            detail = f"{type(exc).__name__}: {exc}"
            code = _classify_error(exc)
            print(f"Scan job {scan_id} FAILED [{code}]: {detail}\n{tb}")
            with _lock:
                _jobs[scan_id] = {
                    "status": "failed",
                    "result": None,
                    "error": public_error_from_exception(exc),
                    "error_code": code,
                    "error_detail": detail[:2000],
                    "finished_at": time.time(),
                }

    __import__("threading").Thread(target=_run, daemon=True).start()
    return {"scan_id": scan_id, "status": "processing"}


def get_job(scan_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(scan_id)
        if not job:
            return None
        payload: dict[str, Any] = {"scan_id": scan_id, "status": job["status"]}
        if job["status"] == "completed" and job["result"] is not None:
            payload["result"] = job["result"]
        if job["status"] == "failed":
            if job.get("error"):
                payload["error"] = job["error"]
            if job.get("error_code"):
                payload["error_code"] = job["error_code"]
            # Server-to-server only (frontend pipeline stores this; never shown in UI).
            if job.get("error_detail"):
                payload["error_detail"] = job["error_detail"]
        return payload
