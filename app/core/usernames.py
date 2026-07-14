"""Username helpers for login and account creation."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_USERNAME_SAFE = re.compile(r"[^a-z0-9_]+")


def sanitize_username_base(value: str) -> str:
    base = _USERNAME_SAFE.sub("", value.strip().lower())[:50]
    return base if len(base) >= 3 else ""


def username_from_email(email: str) -> str:
    local = email.split("@")[0]
    return sanitize_username_base(local) or "user"


async def find_user_by_login(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip().lower()
    if "@" in ident:
        result = await db.execute(select(User).where(User.email == ident))
    else:
        result = await db.execute(select(User).where(User.username == ident))
    return result.scalar_one_or_none()


async def unique_username(db: AsyncSession, base: str) -> str:
    candidate = sanitize_username_base(base) or "user"
    if len(candidate) < 3:
        candidate = f"user_{candidate}"[:50]
    original = candidate
    n = 2
    while True:
        exists = await db.execute(select(User).where(User.username == candidate))
        if not exists.scalar_one_or_none():
            return candidate
        suffix = f"_{n}"
        candidate = f"{original[: 50 - len(suffix)]}{suffix}"
        n += 1
