from uuid import UUID

import httpx
from fastapi import HTTPException
from jose import jwt

from app.core.config import get_settings

settings = get_settings()


def _headers(service: bool = False) -> dict[str, str]:
    key = settings.supabase_service_role_key if service else settings.supabase_anon_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def create_user(email: str, password: str) -> UUID:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=_headers(service=True),
            json={"email": email, "password": password, "email_confirm": True},
        )
    if res.status_code >= 400:
        detail = res.json().get("msg") or res.json().get("message") or res.text
        raise HTTPException(status_code=400, detail=f"Supabase user create failed: {detail}")
    return UUID(res.json()["id"])


async def sign_in(email: str, password: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=password",
            headers=_headers(),
            json={"email": email, "password": password},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return res.json()


async def refresh_session(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=refresh_token",
            headers=_headers(),
            json={"refresh_token": refresh_token},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return res.json()


async def update_password(supabase_user_id: UUID, new_password: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.put(
            f"{settings.supabase_url}/auth/v1/admin/users/{supabase_user_id}",
            headers=_headers(service=True),
            json={"password": new_password},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=400, detail="Could not update password in Supabase")


def get_supabase_user_id(access_token: str) -> UUID:
    payload = jwt.decode(
        access_token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )
    return UUID(payload["sub"])
