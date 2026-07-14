from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal_timeline import DealTimeline
from app.schemas.deal import DEAL_STAGE_LABELS


def stage_label(status: str) -> str:
    return DEAL_STAGE_LABELS.get(status, status.replace("_", " ").title())


async def log_deal_timeline(
    db: AsyncSession,
    *,
    deal_id: UUID,
    company_id: UUID,
    event_type: str,
    description: str,
    created_by_id: UUID | None = None,
    metadata: dict | None = None,
) -> DealTimeline:
    entry = DealTimeline(
        deal_id=deal_id,
        company_id=company_id,
        event_type=event_type,
        description=description,
        created_by_id=created_by_id,
        meta=metadata,
    )
    db.add(entry)
    await db.flush()
    return entry
