"""Seed default roles. Run: python -m scripts.seed_roles

Updates permissions on existing roles so drift stays in sync with ROLE_PERMISSIONS.
"""
import asyncio

from sqlalchemy import select

from app.core.deps import ROLE_PERMISSIONS
from app.db.session import AsyncSessionLocal
from app.models.role import Role


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for name, permissions in ROLE_PERMISSIONS.items():
            existing = await db.execute(select(Role).where(Role.name == name))
            role = existing.scalar_one_or_none()
            if role:
                role.permissions = permissions
            else:
                db.add(Role(name=name, permissions=permissions))
        await db.commit()
        print("Roles seeded/updated:", ", ".join(ROLE_PERMISSIONS.keys()))


if __name__ == "__main__":
    asyncio.run(seed())
