"""Transactional email via Resend.

When RESEND_API_KEY is not set, runs in mock mode: emails are logged to the
console instead of being sent, so the full flow works in development without an
account. All send helpers swallow errors — email must never break the request
that triggered it.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
) -> tuple[bool, str | None]:
    """Send an email. Returns (success, error_message)."""
    if not to:
        return False, "No recipient email"

    provider = settings.email_provider_name
    if provider == "mock":
        hint = settings.email_config_hint() or "Email is not configured."
        logger.warning("[EMAIL NOT SENT] %s to=%s", hint, to)
        return False, hint

    if provider == "smtp":
        return await _send_via_smtp(to, subject, html, attachments)
    if provider == "sendgrid":
        return await _send_via_sendgrid(to, subject, html, attachments)

    return await _send_via_resend(to, subject, html, attachments)


async def _send_via_smtp(
    to: str,
    subject: str,
    html: str,
    attachments: list[dict] | None = None,
) -> tuple[bool, str | None]:
    from_addr = settings.email_from or settings.smtp_user
    from_header = f"{settings.email_from_name} <{from_addr}>"

    def _sync_send() -> None:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(html, "html", "utf-8"))
        msg.attach(alt)
        if attachments:
            from email.mime.application import MIMEApplication

            for att in attachments:
                raw = base64.b64decode(att["content"])
                part = MIMEApplication(raw, Name=att.get("filename", "attachment"))
                part["Content-Disposition"] = f'attachment; filename="{att.get("filename", "file")}"'
                msg.attach(part)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_addr, [to], msg.as_string())

    try:
        await asyncio.to_thread(_sync_send)
        return True, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("SMTP send error: %s", exc)
        return False, str(exc)


async def _send_via_sendgrid(
    to: str,
    subject: str,
    html: str,
    attachments: list[dict] | None = None,
) -> tuple[bool, str | None]:
    from_addr = settings.email_from or settings.smtp_user
    if not from_addr:
        return False, "Set EMAIL_FROM in .env to your verified sender email."

    payload: dict = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_addr, "name": settings.email_from_name},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    if attachments:
        payload["attachments"] = [
            {
                "content": att["content"],
                "filename": att.get("filename", "attachment"),
                "type": "application/pdf",
                "disposition": "attachment",
            }
            for att in attachments
        ]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                json=payload,
                timeout=20.0,
            )
        if resp.status_code >= 400:
            detail = resp.text
            try:
                errors = resp.json().get("errors", [])
                if errors:
                    detail = errors[0].get("message", detail)
            except Exception:
                pass
            logger.warning("SendGrid send failed (%s): %s", resp.status_code, detail)
            return False, str(detail)
        return True, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("SendGrid send error: %s", exc)
        return False, str(exc)


async def _send_via_resend(
    to: str,
    subject: str,
    html: str,
    attachments: list[dict] | None = None,
) -> tuple[bool, str | None]:
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
            detail = resp.text
            try:
                detail = resp.json().get("message", detail)
            except Exception:
                pass
            logger.warning("Resend send failed (%s): %s", resp.status_code, detail)
            return False, str(detail)
        return True, None
    except Exception as exc:  # noqa: BLE001 — email must never break the request
        logger.warning("Resend send error: %s", exc)
        return False, str(exc)


def pdf_attachment(filename: str, data: bytes) -> dict:
    return {"filename": filename, "content": base64.b64encode(data).decode("ascii")}


def split_subject_body(content: str, default_subject: str) -> tuple[str, str]:
    """Extract a leading 'Subject: ...' line from drafted content, if present."""
    lines = content.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip() or default_subject
        body = "\n".join(lines[1:]).strip()
        return subject, body
    return default_subject, content.strip()


async def send_custom_email(to: str, subject: str, body_text: str) -> tuple[bool, str | None]:
    """Send a plain-text-ish email (newlines -> <br>) wrapped in the AgencyFlow template."""
    html = _wrap(subject, body_text.replace("\n", "<br>"))
    return await send_email(to, subject, html)


async def send_owner_credentials_email(
    to: str, username: str, workspace: str, temporary_password: str
) -> tuple[bool, str | None]:
    login_url = f"{settings.frontend_url}/login"
    body = (
        f"<p>Your agency workspace <strong>{workspace}</strong> is ready on AgencyFlow.</p>"
        f"<p>Sign in with:</p>"
        f"<ul>"
        f"<li><strong>Username:</strong> {username}</li>"
        f"<li><strong>Temporary password:</strong> <code>{temporary_password}</code></li>"
        f"</ul>"
        f"<p>You can sign in with this password anytime. "
        f"After login, you can optionally set your own password from the dashboard.</p>"
        f'<p><a style="{_BTN}" href="{login_url}">Sign in to AgencyFlow</a></p>'
    )
    return await send_email(
        to,
        "Your AgencyFlow login details",
        _wrap("Workspace created", body),
    )


async def send_welcome_email(to: str, first_name: str, workspace: str) -> bool:
    body = (
        f"<p>Hi {first_name or 'there'},</p>"
        f"<p>Your workspace <strong>{workspace}</strong> is ready on AgencyFlow. "
        "Manage leads, clients, projects, GST invoices, and your client portal — all in one place.</p>"
        f'<p><a style="{_BTN}" href="{settings.frontend_url}/login">Open your workspace</a></p>'
    )
    ok, _ = await send_email(to, "Welcome to AgencyFlow", _wrap("Welcome aboard", body))
    return ok


async def send_password_reset_email(to: str, reset_link: str) -> bool:
    body = (
        "<p>We received a request to reset your AgencyFlow password.</p>"
        f'<p><a style="{_BTN}" href="{reset_link}">Reset password</a></p>'
        "<p style='font-size:13px;color:#64748b;'>This link is valid for 30 minutes. "
        "If you didn't request this, you can safely ignore this email.</p>"
    )
    ok, _ = await send_email(to, "Reset your AgencyFlow password", _wrap("Password reset", body))
    return ok


async def send_staff_invite_email(
    to: str,
    first_name: str,
    workspace: str,
    invite_link: str,
    *,
    inviter_name: str,
    inviter_email: str,
    decline_link: str,
) -> tuple[bool, str | None]:
    body = (
        "<p>Hello,</p>"
        f"<p>You have been invited to join <strong>{workspace}</strong>'s AgencyFlow workspace. "
        "Once you accept the invitation link, you will be associated with that account.</p>"
        f'<p><a style="{_BTN}" href="{invite_link}">Join now</a></p>'
        f"<p style='font-size:13px;color:#64748b;'>If the button does not work, copy and paste this link into your browser:<br>"
        f'<a href="{invite_link}">{invite_link}</a></p>'
        f"<p style='font-size:13px;color:#64748b;'>If you do not wish to accept, you can "
        f'<a href="{decline_link}">decline</a> the invitation.</p>'
        f"<p style='font-size:13px;color:#64748b;'>This link expires in 7 days.</p>"
        f"<p style='font-size:13px;color:#64748b;'>Questions? Contact {inviter_email}</p>"
    )
    return await send_email(to, f"Join {workspace} on AgencyFlow", _wrap("Team invite", body))


async def send_account_confirm_email(
    to: str, first_name: str, confirm_link: str
) -> tuple[bool, str | None]:
    body = (
        f"<p>Hi {first_name or 'there'},</p>"
        f"<p>Welcome to AgencyFlow! Confirm your account by clicking below:</p>"
        f'<p><a style="{_BTN}" href="{confirm_link}">Confirm your account</a></p>'
        "<p style='font-size:13px;color:#64748b;'>This link is valid for 24 hours.</p>"
    )
    return await send_email(to, "Confirm your AgencyFlow account", _wrap("Almost there", body))


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
    ok, _ = await send_email(
        to,
        f"Invoice {invoice_number} from {company_name}",
        _wrap("Your invoice", body),
        attachments=[pdf_attachment(f"{invoice_number}.pdf", pdf_bytes)],
    )
    return ok
