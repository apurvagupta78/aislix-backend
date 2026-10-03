from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import auth


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://projectref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    auth._token_cache.clear()


def test_fetchable_urls(supabase_env, monkeypatch):
    auth.assert_fetchable_url("data:image/jpeg;base64,AAAA")
    auth.assert_fetchable_url("https://projectref.supabase.co/storage/v1/object/sign/scan-images/a.jpg?token=x")
    auth.assert_fetchable_url("https://other.supabase.co/storage/v1/object/a.jpg")
    for bad in (
        "http://projectref.supabase.co/a.jpg",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/a.jpg",
        "https://evil.example.com/a.jpg",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError):
            auth.assert_fetchable_url(bad)
    monkeypatch.setenv("BACKEND_FETCH_ALLOWED_HOSTS", "cdn.aislix.com")
    auth.assert_fetchable_url("https://cdn.aislix.com/a.jpg")


def test_edge_ip_uses_last_hop():
    request = SimpleNamespace(headers={"x-forwarded-for": "1.1.1.1, 9.9.9.9"}, client=None)
    assert auth.edge_ip(request) == "9.9.9.9"


def test_window_limiter():
    limiter = auth.WindowLimiter()
    assert limiter.allow("k", 2, 60)
    assert limiter.allow("k", 2, 60)
    assert not limiter.allow("k", 2, 60)
    assert limiter.allow("other", 2, 60)


def _client():
    import main

    return TestClient(main.app)


def test_enforce_rejects_missing_and_invalid_tokens(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": None)
    client = _client()
    assert client.post("/scan", json={}).status_code == 401
    assert client.post("/scan", json={}, headers={"Authorization": "Bearer a.b.c"}).status_code == 401
    assert client.get("/documents/read/abc").status_code == 401


def test_enforce_accepts_valid_token(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": "user-1")
    client = _client()
    response = client.post("/scan", json={}, headers={"Authorization": "Bearer a.b.c"})
    assert response.status_code == 400
    assert client.get("/documents/read/abc", headers={"Authorization": "Bearer a.b.c"}).status_code == 404


def test_observe_mode_lets_requests_through(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "observe")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": None)
    assert _client().post("/scan", json={}).status_code == 400


def test_default_mode_is_enforce(monkeypatch):
    monkeypatch.delenv("BACKEND_AUTH_MODE", raising=False)
    assert auth.auth_mode() == "enforce"


SCAN = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
ORG = "33333333-3333-3333-3333-333333333333"


def test_user_can_access_scan_reads_as_the_user(supabase_env, monkeypatch):
    auth._access_cache.clear()
    visible: list[dict] = []
    calls: list[tuple[str, str, str]] = []

    def rows(path, token, key):
        calls.append((path, token, key))
        return visible

    monkeypatch.setattr(auth, "_rest_rows_as_user", rows)
    assert not auth.user_can_access_scan(USER, SCAN, "user.jwt.token", "anon-key")
    assert calls[-1] == (f"shelf_scans?id=eq.{SCAN}&select=id", "user.jwt.token", "anon-key")
    auth._access_cache.clear()
    visible.append({"id": SCAN})
    assert auth.user_can_access_scan(USER, SCAN, "user.jwt.token", "anon-key")
    assert not auth.user_can_access_scan(USER, "not-a-uuid", "user.jwt.token", "anon-key")
    assert not auth.user_can_access_scan(USER, SCAN, "", "anon-key")


def test_api_key_falls_back_to_caller_publishable_key(monkeypatch):
    for name in ("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    request = SimpleNamespace(headers={"x-supabase-apikey": "sb_publishable_x"})
    assert auth._api_key(request) == "sb_publishable_x"
    monkeypatch.setenv("SUPABASE_ANON_KEY", "server-anon")
    assert auth._api_key(request) == "server-anon"
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert auth._supabase_url() == auth.DEFAULT_SUPABASE_URL


def test_scan_status_hidden_from_other_orgs(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": USER)
    monkeypatch.setattr(auth, "user_can_access_scan", lambda user_id, scan_id, token, key: False)
    client = _client()
    headers = {"Authorization": "Bearer a.b.c"}
    assert client.get(f"/scan/{SCAN}", headers=headers).status_code == 404
    response = client.post(
        "/scan",
        json={"scan_id": SCAN, "image_urls": ["data:image/jpeg;base64,AAAA"], "category": "Personal Care"},
        headers=headers,
    )
    assert response.status_code == 404


def test_document_jobs_are_owner_only(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    auth.remember_job_owner("job-1", USER)
    auth.require_job_owner("job-1", USER)
    with pytest.raises(Exception):
        auth.require_job_owner("job-1", "someone-else")


def test_landing_convert_requires_sign_in(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": None)
    response = _client().post("/landing/convert", json={"session_token": "abcdefgh12345678", "user_id": USER})
    assert response.status_code == 401


def test_landing_share_persist_is_retired(supabase_env):
    assert _client().post("/landing/share/persist", json={}).status_code == 410


def test_scan_rejects_non_storage_image_url(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    monkeypatch.setattr(auth, "verify_user_token", lambda token, key="": "user-1")
    monkeypatch.setattr(auth, "user_can_access_scan", lambda user_id, scan_id, token, key: True)
    response = _client().post(
        "/scan",
        json={"scan_id": "s1", "image_urls": ["https://evil.example.com/a.jpg"], "category": "Personal Care"},
        headers={"Authorization": "Bearer a.b.c"},
    )
    assert response.status_code == 400


def test_public_routes_stay_open(supabase_env, monkeypatch):
    monkeypatch.setenv("BACKEND_AUTH_MODE", "enforce")
    client = _client()
    assert client.get("/").status_code == 200
    assert client.get("/categories").status_code == 200
    assert client.get("/planogram/csv-template").status_code == 200
