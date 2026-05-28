from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.user import User


async def get_starter_plan(db: AsyncSession) -> SubscriptionPlan | None:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == "Starter"))
    return result.scalar_one_or_none()


async def assert_can_add_user(db: AsyncSession, company_id: UUID) -> None:
    company = await db.get(Company, company_id)
    if not company or not company.subscription_plan_id:
        return
    plan = await db.get(SubscriptionPlan, company.subscription_plan_id)
    if not plan:
        return
    count = await db.execute(select(func.count()).select_from(User).where(User.company_id == company_id))
    if count.scalar_one() >= plan.max_users:
        raise HTTPException(
            status_code=400,
            detail=f"User limit reached ({plan.max_users}) for plan {plan.name}",
        )


async def assert_can_add_client(db: AsyncSession, company_id: UUID) -> None:
    company = await db.get(Company, company_id)
    if not company or not company.subscription_plan_id:
        return
    plan = await db.get(SubscriptionPlan, company.subscription_plan_id)
    if not plan:
        return
    count = await db.execute(select(func.count()).select_from(Client).where(Client.company_id == company_id))
    if count.scalar_one() >= plan.max_clients:
        raise HTTPException(
            status_code=400,
            detail=f"Client limit reached ({plan.max_clients}) for plan {plan.name}",
        )
