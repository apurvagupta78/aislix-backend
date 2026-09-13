"""Email demo audit reports with share link (Resend)."""

from __future__ import annotations

import base64
import os
from urllib.parse import quote

import requests

from app.landing_email import FROM_EMAIL, RESEND_API_KEY, APP_ORIGIN

EMAIL_BODY = (
    "Your Aislix shelf audit is ready. Review the attached report for KPI results, "
    "shelf findings, issues, recommendations and supporting analysis."
)


def _share_url(session_token: str) -> str:
    return f"{APP_ORIGIN}/share/{quote(session_token)}"


def send_demo_audit_report_email(
    *,
    recipient: str,
    session_token: str,
    store_name: str | None = None,
    audit_date: str | None = None,
    message: str | None = None,
    pdf_bytes: bytes | None = None,
) -> tuple[bool, str | None]:
    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY not configured"
    store = store_name or "Store"
    date_label = (audit_date or "")[:10] or "Recent"
    subject = f"Aislix Shelf Audit Report — {store} — {date_label}"
    share = _share_url(session_token)
    note = f"<p>{message}</p>" if message else ""
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0f172a;">
      <h2 style="color:#0f172a;">Aislix Shelf Audit Report</h2>
      {note}
      <p>{EMAIL_BODY}</p>
      <p><a href="{share}" style="color:#1e3a5f;font-weight:600;">View audit report online</a></p>
      <p style="font-size:12px;color:#64748b;">This link works without login.</p>
    </div>
    """
    payload: dict = {
        "from": FROM_EMAIL,
        "to": [recipient],
        "subject": subject,
        "html": html,
    }
    if pdf_bytes:
        payload["attachments"] = [
            {
                "filename": f"aislix-audit-{session_token[:8]}.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ]
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        if response.status_code in {200, 201}:
            return True, None
        return False, f"Resend {response.status_code}: {response.text[:200]}"
    except Exception as exc:
        return False, str(exc)
