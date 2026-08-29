"""Tests for landing onboarding email helpers."""

from __future__ import annotations

from app.landing_email import build_signup_url, send_landing_onboarding_email


def test_build_signup_url_includes_email_and_session():
    url = build_signup_url(email="test@example.com", landing_session_id="abc123")
    assert "test%40example.com" in url or "test@example.com" in url
    assert "landing_session_id=abc123" in url
    assert url.startswith("https://")


def test_send_returns_signup_url_when_resend_missing(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "")
    sent, err, url = send_landing_onboarding_email(
        email="test@example.com",
        name="Test",
        landing_session_id="abc123",
    )
    assert sent is False
    assert url
    assert "signup" in url
