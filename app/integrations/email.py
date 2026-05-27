import httpx
from fastapi import HTTPException

from app.core.config import get_settings

settings = get_settings()


async def send_password_reset_email(to_email: str, reset_url: str) -> None:
    if not settings.resend_api_key:
        raise HTTPException(status_code=500, detail="Resend API key is not configured")

    html = f"""
    <p>Hello,</p>
    <p>We received a request to reset your AgencyFlow password.</p>
    <p><a href="{reset_url}">Reset your password</a></p>
    <p>This link expires in 30 minutes. If you did not request this, ignore this email.</p>
    """

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": "Reset your AgencyFlow password",
                "html": html,
            },
        )

    if res.status_code >= 400:
        detail = res.json().get("message", res.text)
        raise HTTPException(status_code=502, detail=f"Failed to send reset email: {detail}")
