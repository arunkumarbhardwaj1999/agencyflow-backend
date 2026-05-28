"""Seed subscription plans. Run: python -m scripts.seed_plans"""
import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.subscription_plan import SubscriptionPlan

PLANS = [
    {
        "name": "Starter",
        "price": 0,
        "max_users": 10,
        "max_clients": 100,
        "features": {
            "leads": True,
            "clients": True,
            "projects": True,
            "invoices": True,
            "dashboard": True,
            "portal": True,
        },
    },
    {
        "name": "Growth",
        "price": 2999,
        "max_users": 25,
        "max_clients": 500,
        "features": {"leads": True, "clients": True, "projects": True, "invoices": True, "portal": True},
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for plan_data in PLANS:
            existing = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.name == plan_data["name"])
            )
            if existing.scalar_one_or_none():
                continue
            db.add(SubscriptionPlan(**plan_data))
        await db.commit()
        print("Plans seeded:", ", ".join(p["name"] for p in PLANS))


if __name__ == "__main__":
    asyncio.run(seed())
