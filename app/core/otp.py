"""Phone OTP — plain SMS (Twilio / MSG91). WhatsApp is not used for signup OTP."""

from __future__ import annotations

import logging
import secrets

from app.core.config import get_settings
from app.core.security import hash_token
from app.core.sms import SMSError, normalize_sms_phone, send_msg91_otp, send_sms

logger = logging.getLogger("agencyflow.otp")
settings = get_settings()


def generate_otp_code() -> str:
    return f"{secrets.randbelow(900_000) + 100_000}"


def hash_otp(code: str) -> str:
    return hash_token(code.strip())


async def send_otp_to_phone(phone: str, code: str, *, recipient_name: str = "there") -> tuple[bool, str | None]:
    _ = recipient_name
    message = f"Your AgencyFlow verification code is {code}. Valid for 10 minutes."

    if not settings.sms_enabled:
        logger.info("[OTP MOCK SMS] phone=%s (code omitted)", phone)
        return True, "mock"

    try:
        if (settings.sms_provider or "").strip().lower() == "msg91":
            _, digits = normalize_sms_phone(phone)
            result = await send_msg91_otp(digits, code)
        else:
            result = await send_sms(phone, message)
        if result.get("status") in ("sent", "mock"):
            return True, None if result.get("status") == "sent" else "mock"
    except SMSError as exc:
        logger.warning("OTP SMS send failed: %s", exc)
        return False, str(exc)

    return False, "SMS was not accepted by the provider"


async def send_otp_to_email(email: str, code: str, workspace: str) -> tuple[bool, str | None]:
    from app.core.email import send_custom_email

    subject = "Your AgencyFlow verification code"
    body = (
        f"Your verification code for joining {workspace} is:\n\n"
        f"{code}\n\n"
        "Enter this code on the invite page. Valid for 10 minutes."
    )
    ok, err = await send_custom_email(email, subject, body)
    if not ok:
        logger.info("[OTP MOCK EMAIL] email=%s (code omitted)", email)
        return True, err or "logged"
    return True, None
