"""Seed default roles. Run: python -m scripts.seed_roles"""
import asyncio

from sqlalchemy import select

from app.core.deps import ROLE_PERMISSIONS
from app.db.session import AsyncSessionLocal
from app.models.role import Role


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for name, permissions in ROLE_PERMISSIONS.items():
            existing = await db.execute(select(Role).where(Role.name == name))
            if existing.scalar_one_or_none():
                continue
            db.add(Role(name=name, permissions=permissions))
        await db.commit()
        print("Roles seeded:", ", ".join(ROLE_PERMISSIONS.keys()))


if __name__ == "__main__":
    asyncio.run(seed())
