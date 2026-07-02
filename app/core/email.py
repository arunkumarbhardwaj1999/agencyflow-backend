"""Transactional email via Resend.

When RESEND_API_KEY is not set, runs in mock mode: emails are logged to the
console instead of being sent, so the full flow works in development without an
account. All send helpers swallow errors — email must never break the request
that triggered it.
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("agencyflow.email")
settings = get_settings()

RESEND_ENDPOINT = "https://api.resend.com/emails"

_BASE_STYLE = (
    "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "color:#0f172a;line-height:1.6;"
)
_BTN = (
    "display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);"
    "color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;"
    "font-weight:600;"
)


def _wrap(title: str, body_html: str) -> str:
    return (
        f'<div style="max-width:520px;margin:0 auto;{_BASE_STYLE}">'
        f'<h1 style="font-size:20px;color:#4f46e5;">{title}</h1>'
        f"{body_html}"
        '<hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">'
        '<p style="font-size:12px;color:#94a3b8;">AgencyFlow — CRM for Indian digital agencies.</p>'
        "</div>"
    )


async def send_email(
    to: str,
    subject: str,
    html: str,
    attachments: list[dict] | None = None,
) -> bool:
    """Send an email. Returns True on success (or in mock mode)."""
    if not to:
        return False

    if not settings.email_enabled:
        logger.info("[EMAIL MOCK] to=%s subject=%s", to, subject)
        return True

    payload: dict = {
        "from": f"{settings.email_from_name} <{settings.email_from}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
                timeout=15.0,
            )
        if resp.status_code >= 400:
            logger.warning("Resend send failed (%s): %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — email must never break the request
        logger.warning("Resend send error: %s", exc)
        return False


def pdf_attachment(filename: str, data: bytes) -> dict:
    return {"filename": filename, "content": base64.b64encode(data).decode("ascii")}


async def send_welcome_email(to: str, first_name: str, workspace: str) -> bool:
    body = (
        f"<p>Hi {first_name or 'there'},</p>"
        f"<p>Your workspace <strong>{workspace}</strong> is ready on AgencyFlow. "
        "Manage leads, clients, projects, GST invoices, and your client portal — all in one place.</p>"
        f'<p><a style="{_BTN}" href="{settings.frontend_url}/login">Open your workspace</a></p>'
    )
    return await send_email(to, "Welcome to AgencyFlow", _wrap("Welcome aboard", body))


async def send_password_reset_email(to: str, reset_link: str) -> bool:
    body = (
        "<p>We received a request to reset your AgencyFlow password.</p>"
        f'<p><a style="{_BTN}" href="{reset_link}">Reset password</a></p>'
        "<p style='font-size:13px;color:#64748b;'>This link is valid for 30 minutes. "
        "If you didn't request this, you can safely ignore this email.</p>"
    )
    return await send_email(to, "Reset your AgencyFlow password", _wrap("Password reset", body))


async def send_invoice_email(
    to: str,
    invoice_number: str,
    company_name: str,
    pdf_bytes: bytes,
    pay_link: str | None = None,
) -> bool:
    pay_html = (
        f'<p><a style="{_BTN}" href="{pay_link}">Pay now</a></p>' if pay_link else ""
    )
    body = (
        f"<p>Please find attached invoice <strong>{invoice_number}</strong> from {company_name}.</p>"
        f"{pay_html}"
        "<p style='font-size:13px;color:#64748b;'>The tax invoice is attached as a PDF.</p>"
    )
    return await send_email(
        to,
        f"Invoice {invoice_number} from {company_name}",
        _wrap("Your invoice", body),
        attachments=[pdf_attachment(f"{invoice_number}.pdf", pdf_bytes)],
    )
