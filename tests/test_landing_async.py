import time

from fastapi.testclient import TestClient

import main
from app import jobs


def _put(job_id: str, **job):
    with jobs._lock:
        jobs._jobs[job_id] = job


def test_status_unknown_token_is_404():
    client = TestClient(main.app)
    assert client.get("/landing/scan/nope/status").status_code == 404


def test_status_returns_result_when_completed():
    _put("landing:tok-done", status="completed", result={"scan_id": "abc"}, finished_at=time.time())
    body = TestClient(main.app).get("/landing/scan/tok-done/status").json()
    assert body == {"landing_session_id": "tok-done", "status": "completed", "result": {"scan_id": "abc"}}


def test_status_hides_internal_error_detail():
    _put(
        "landing:tok-fail",
        status="failed",
        error="We couldn't analyze this shelf image right now.",
        error_detail="Traceback secret",
        finished_at=time.time(),
    )
    body = TestClient(main.app).get("/landing/scan/tok-fail/status").json()
    assert body["status"] == "failed"
    assert "error_detail" not in body
    assert "Traceback" not in str(body)


def test_stale_landing_jobs_are_pruned_but_others_kept():
    old = time.time() - jobs.LANDING_JOB_TTL_SECONDS - 10
    _put("landing:stale", status="completed", result={}, finished_at=old)
    _put("scan-keep", status="completed", result={}, finished_at=old)
    jobs.start_job("landing:new", lambda: {"ok": True})
    assert jobs.get_job("landing:stale") is None
    assert jobs.get_job("scan-keep") is not None
