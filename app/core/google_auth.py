"""Verify Google Sign-In ID tokens (OAuth 2.0 credential from GSI)."""

import httpx

from app.core.config import get_settings


class GoogleAuthError(Exception):
    pass


async def verify_google_id_token(id_token: str) -> dict:
    settings = get_settings()
    if not settings.google_client_id:
        raise GoogleAuthError("Google sign-in is not available right now")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise GoogleAuthError("Google sign-in failed. Please try again")

    data = resp.json()
    if data.get("aud") != settings.google_client_id:
        raise GoogleAuthError("Google sign-in failed. Please try again")
    if str(data.get("email_verified", "")).lower() != "true":
        raise GoogleAuthError("Please verify your Google email, then try again")

    email = data.get("email")
    if not email:
        raise GoogleAuthError("Google sign-in did not return an email address")

    return data
