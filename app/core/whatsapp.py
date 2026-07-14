"""WhatsApp notifications via Meta Cloud API.

When credentials are not configured, runs in mock mode — messages are logged to
the database with status ``mock`` so the full flow can be tested locally.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("agencyflow.whatsapp")
settings = get_settings()

GRAPH_BASE = "https://graph.facebook.com/v21.0"

# Free-text templates used in mock mode and as fallback copy.
TEMPLATES = {
    "payment_reminder": (
        "Hi {name}, this is a friendly reminder that invoice {invoice_number} "
        "of ₹{amount} is due on {due_date}. Please let us know if you have questions."
    ),
    "invoice_ready": (
        "Hi {name}, your invoice {invoice_number} for ₹{amount} is ready. "
        "We've emailed the PDF — reply here if you need help."
    ),
    "payment_received": (
        "Hi {name}, thank you! We've received your payment of ₹{amount} for invoice "
        "{invoice_number}. A receipt has been emailed to you."
    ),
    "task_update": (
        'Hi {name}, there\'s an update on your project "{project_title}": {detail}'
    ),
}

# Meta-approved template names (must match templates created in Meta Business Manager).
META_TEMPLATE_NAMES = {
    "payment_reminder": "payment_reminder",
    "invoice_ready": "invoice_ready",
    "payment_received": "payment_received",
    "task_update": "task_update",
}


class WhatsAppError(Exception):
    pass


def normalize_phone(phone: str) -> str:
    """Strip spaces/dashes and ensure digits only (with optional leading +)."""
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if cleaned.startswith("+"):
        return cleaned[1:]
    if cleaned.startswith("0"):
        return cleaned[1:]
    if len(cleaned) == 10:
        return f"91{cleaned}"
    return cleaned


def render_template(name: str, **kwargs: str) -> str:
    tpl = TEMPLATES.get(name)
    if not tpl:
        raise WhatsAppError(f"Unknown template: {name}")
    return tpl.format(**kwargs)


def _template_components(template_key: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Build Meta template body parameters from our template keys."""
    if template_key == "payment_reminder":
        return [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": params.get("name", "Client")},
                    {"type": "text", "text": params.get("invoice_number", "")},
                    {"type": "text", "text": params.get("amount", "")},
                    {"type": "text", "text": params.get("due_date", "")},
                ],
            }
        ]
    if template_key == "invoice_ready":
        return [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": params.get("name", "Client")},
                    {"type": "text", "text": params.get("invoice_number", "")},
                    {"type": "text", "text": params.get("amount", "")},
                ],
            }
        ]
    if template_key == "payment_received":
        return [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": params.get("name", "Client")},
                    {"type": "text", "text": params.get("amount", "")},
                    {"type": "text", "text": params.get("invoice_number", "")},
                ],
            }
        ]
    if template_key == "task_update":
        return [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": params.get("name", "Client")},
                    {"type": "text", "text": params.get("project_title", "")},
                    {"type": "text", "text": params.get("detail", "")},
                ],
            }
        ]
    return []


async def send_template(
    phone: str,
    template_key: str,
    params: dict[str, str],
) -> dict:
    """Send a Meta-approved WhatsApp template message."""
    to = normalize_phone(phone)
    if not to:
        raise WhatsAppError("Invalid phone number")

    meta_name = META_TEMPLATE_NAMES.get(template_key)
    if not meta_name:
        raise WhatsAppError(f"No Meta template mapped for: {template_key}")

    if not settings.whatsapp_enabled:
        text = render_template(template_key, **params)
        logger.info("[WHATSAPP MOCK TEMPLATE] to=%s template=%s text=%s", to, template_key, text[:120])
        return {"status": "mock", "to": to, "message_id": None, "delivery": "template"}

    url = f"{GRAPH_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": meta_name,
            "language": {"code": settings.whatsapp_template_language},
            "components": _template_components(template_key, params),
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json=payload,
            timeout=15.0,
        )
    if resp.status_code >= 400:
        logger.warning("WhatsApp template failed (%s): %s", resp.status_code, resp.text)
        # Fall back to plain text when template is not yet approved in Meta.
        text = render_template(template_key, **params)
        return await send_text(to, text)
    data = resp.json()
    msg_id = data.get("messages", [{}])[0].get("id")
    return {"status": "template_sent", "to": to, "message_id": msg_id, "delivery": "template"}


async def send_text(phone: str, message: str) -> dict:
    """Send a WhatsApp text message. Returns provider response metadata."""
    to = normalize_phone(phone)
    if not to:
        raise WhatsAppError("Invalid phone number")

    if not settings.whatsapp_enabled:
        logger.info("[WHATSAPP MOCK] to=%s message=%s", to, message[:120])
        return {"status": "mock", "to": to, "message_id": None, "delivery": "text"}

    url = f"{GRAPH_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message[:4096]},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json=payload,
            timeout=15.0,
        )
    if resp.status_code >= 400:
        logger.warning("WhatsApp send failed (%s): %s", resp.status_code, resp.text)
        raise WhatsAppError(f"WhatsApp API error: {resp.text[:200]}")
    data = resp.json()
    msg_id = data.get("messages", [{}])[0].get("id")
    return {"status": "sent", "to": to, "message_id": msg_id, "delivery": "text"}


async def send_otp_code(phone: str, code: str, *, recipient_name: str = "there") -> dict:
    """Send OTP via Meta-approved template (required for delivery in dev/production)."""
    to = normalize_phone(phone)
    if not to:
        raise WhatsAppError("Invalid phone number")

    if not settings.whatsapp_enabled:
        logger.info("[WHATSAPP MOCK OTP] to=%s code=%s", to, code)
        return {"status": "mock", "to": to, "message_id": None, "delivery": "otp"}

    template_name = settings.whatsapp_otp_template.strip() or "jaspers_market_order_confirmation_v1"
    language = settings.whatsapp_otp_template_language or "en_US"
    url = f"{GRAPH_BASE}/{settings.whatsapp_phone_number_id}/messages"

    if template_name == "jaspers_market_order_confirmation_v1":
        # Meta sandbox sample — OTP is sent as the "order number" in {{2}}.
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": recipient_name[:50] or "there"},
                    {"type": "text", "text": code},
                    {"type": "text", "text": "10 minutes"},
                ],
            }
        ]
    elif template_name == "hello_world":
        components = []
        language = "en_US"
    else:
        # Custom authentication template (body {{1}} + copy-code button).
        components = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": code}],
            },
            {
                "type": "button",
                "sub_type": "copy_code",
                "index": "0",
                "parameters": [{"type": "coupon_code", "coupon_code": code}],
            },
        ]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": components,
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json=payload,
            timeout=15.0,
        )
    if resp.status_code >= 400:
        logger.warning("WhatsApp OTP template failed (%s): %s", resp.status_code, resp.text)
        raise WhatsAppError(f"WhatsApp API error: {resp.text[:200]}")
    data = resp.json()
    msg_id = data.get("messages", [{}])[0].get("id")
    return {"status": "sent", "to": to, "message_id": msg_id, "delivery": "otp_template"}


async def send_message(
    *,
    phone: str,
    template_key: str | None = None,
    params: dict[str, str] | None = None,
    text: str | None = None,
    use_template: bool = True,
) -> dict:
    """Send via Meta template when possible, otherwise plain text."""
    if template_key and use_template and template_key in META_TEMPLATE_NAMES:
        return await send_template(phone, template_key, params or {})
    if text:
        return await send_text(phone, text)
    if template_key:
        return await send_text(phone, render_template(template_key, **(params or {})))
    raise WhatsAppError("No message content provided")
