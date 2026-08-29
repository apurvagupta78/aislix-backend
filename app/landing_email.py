"""Send landing-lead onboarding email via Resend."""

from __future__ import annotations

import os

import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
FROM_EMAIL = os.getenv("LANDING_FROM_EMAIL", os.getenv("RESEND_FROM_EMAIL", "Aislix <onboarding@aislix.com>"))
APP_ORIGIN = os.getenv("APP_ORIGIN", os.getenv("PUBLIC_APP_URL", "https://aislix.com")).rstrip("/")


def build_signup_url(*, email: str, landing_session_id: str) -> str:
    from urllib.parse import quote

    params = f"email={quote(email)}&landing_session_id={quote(landing_session_id)}"
    return f"{APP_ORIGIN}/signup?{params}"


def send_landing_onboarding_email(
    *,
    email: str,
    name: str | None = None,
    landing_session_id: str,
) -> tuple[bool, str | None]:
    """Return (sent, error_message)."""
    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY not configured"

    signup_url = build_signup_url(email=email, landing_session_id=landing_session_id)
    greeting = f"Hi {name}," if name else "Hi,"

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0f172a;">
      <h2 style="color:#0f172a;margin-bottom:8px;">Welcome to Aislix</h2>
      <p>{greeting}</p>
      <p>Thanks for trying Aislix shelf intelligence. You're one step away from your free workspace with <strong>3 shelf scans</strong>.</p>
      <p style="margin:24px 0;">
        <a href="{signup_url}" style="background:#0f172a;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block;">
          Create your free Aislix account →
        </a>
      </p>
      <p style="color:#475569;font-size:14px;">Or copy this link:<br><a href="{signup_url}">{signup_url}</a></p>
      <p style="color:#64748b;font-size:13px;margin-top:32px;">If you didn't request this, you can ignore this email.</p>
    </div>
    """

    payload = {
        "from": FROM_EMAIL,
        "to": [email],
        "subject": "Your Aislix free workspace — complete signup",
        "html": html,
    }
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if response.status_code in {200, 201}:
            return True, None
        return False, f"Resend {response.status_code}: {response.text[:200]}"
    except Exception as exc:
        return False, str(exc)
