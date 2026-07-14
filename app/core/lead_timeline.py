from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_timeline import LeadTimeline

LEAD_STATUS_LABELS = {
    "new": "New",
    "contacted": "Contacted",
    "proposal": "Proposal",
    "won": "Won",
    "lost": "Lost",
}


def status_label(status: str) -> str:
    return LEAD_STATUS_LABELS.get(status, status.replace("_", " ").title())


async def log_lead_timeline(
    db: AsyncSession,
    *,
    lead_id: UUID,
    company_id: UUID,
    event_type: str,
    description: str,
    created_by_id: UUID | None = None,
    metadata: dict | None = None,
) -> LeadTimeline:
    entry = LeadTimeline(
        lead_id=lead_id,
        company_id=company_id,
        event_type=event_type,
        description=description,
        created_by_id=created_by_id,
        meta=metadata,
    )
    db.add(entry)
    await db.flush()
    return entry
