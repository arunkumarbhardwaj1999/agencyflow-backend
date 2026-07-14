"""SMS delivery for OTP — Twilio or MSG91 (India). No Meta/WhatsApp required."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.core.config import get_settings

logger = logging.getLogger("agencyflow.sms")
settings = get_settings()


class SMSError(Exception):
    pass


def normalize_sms_phone(phone: str) -> tuple[str, str]:
    """Return (e164_with_plus, digits_only) for India-first numbers."""
    digits = re.sub(r"\D", "", phone.strip())
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = f"91{digits}"
    if not digits.startswith("91") and len(digits) <= 10:
        raise SMSError("Enter a valid 10-digit Indian mobile number")
    return f"+{digits}", digits


def _parse_msg91_response(resp: httpx.Response) -> dict:
    text = (resp.text or "").strip()
    if resp.status_code >= 400:
        raise SMSError(f"SMS provider HTTP {resp.status_code}: {text[:200]}")
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    if text.lower().startswith("error") or "invalid" in text.lower():
        raise SMSError(f"SMS provider error: {text[:200]}")
    return {"type": "success", "message": text}


async def _send_twilio(e164: str, message: str) -> None:
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_from_number
    if not (sid and token and from_number):
        raise SMSError("Twilio is not configured")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            auth=(sid, token),
            data={"To": e164, "From": from_number, "Body": message[:1600]},
            timeout=20.0,
        )
    if resp.status_code >= 400:
        logger.warning("Twilio SMS failed (%s): %s", resp.status_code, resp.text[:300])
        raise SMSError(f"SMS provider error: {resp.text[:200]}")


async def send_msg91_otp(digits: str, code: str) -> dict:
    """Send OTP via MSG91 OTP API (works without custom DLT sender in most trials)."""
    auth_key = settings.msg91_auth_key
    if not auth_key:
        raise SMSError("MSG91 is not configured")

    sender = (settings.msg91_sender_id or "").strip()
    template_id = (settings.msg91_otp_template_id or "").strip()

    async with httpx.AsyncClient() as client:
        if template_id:
            resp = await client.post(
                "https://control.msg91.com/api/v5/otp",
                params={
                    "authkey": auth_key,
                    "template_id": template_id,
                    "mobile": digits,
                    "otp": code,
                    "otp_length": str(len(code)),
                },
                timeout=20.0,
            )
        else:
            params: dict[str, str] = {
                "authkey": auth_key,
                "mobile": digits,
                "otp": code,
                "otp_length": str(len(code)),
                "otp_expiry": "10",
            }
            if sender:
                params["sender"] = sender
            resp = await client.get(
                "https://api.msg91.com/api/sendotp.php",
                params=params,
                timeout=20.0,
            )

    data = _parse_msg91_response(resp)
    if str(data.get("type", "")).lower() == "error":
        raise SMSError(str(data.get("message", "MSG91 rejected the OTP request")))
    logger.info("MSG91 OTP accepted for %s: %s", digits, data.get("message", "ok"))
    return {"status": "sent", "to": f"+{digits}", "provider": "msg91", "ref": data.get("message")}


async def _send_msg91_text(digits: str, message: str) -> None:
    """Plain SMS — requires DLT-approved sender in India."""
    auth_key = settings.msg91_auth_key
    sender = settings.msg91_sender_id or "SMSIND"
    if not auth_key:
        raise SMSError("MSG91 is not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://control.msg91.com/api/sendhttp.php",
            params={
                "authkey": auth_key,
                "mobiles": digits,
                "message": message,
                "sender": sender,
                "route": "4",
                "country": "91",
            },
            timeout=20.0,
        )
    data = _parse_msg91_response(resp)
    logger.info("MSG91 text SMS response for %s: %s", digits, data)


async def send_sms(phone: str, message: str) -> dict:
    """Send a plain text SMS. Uses SMS_PROVIDER from settings."""
    e164, digits = normalize_sms_phone(phone)
    provider = (settings.sms_provider or "").strip().lower()

    if not provider:
        logger.info("[SMS MOCK] to=%s message=%s", e164, message[:120])
        return {"status": "mock", "to": e164}

    if provider == "twilio":
        await _send_twilio(e164, message)
        return {"status": "sent", "to": e164, "provider": "twilio"}

    if provider == "msg91":
        await _send_msg91_text(digits, message)
        return {"status": "sent", "to": e164, "provider": "msg91"}

    raise SMSError(f"Unknown SMS_PROVIDER: {provider}")
