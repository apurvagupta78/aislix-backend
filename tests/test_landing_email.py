"""Tests for landing onboarding email helpers."""

from __future__ import annotations

from app.landing_email import build_signup_url


def test_build_signup_url_includes_email_and_session():
    url = build_signup_url(email="test@example.com", landing_session_id="abc123")
    assert "test%40example.com" in url or "test@example.com" in url
    assert "landing_session_id=abc123" in url
    assert url.startswith("https://")
