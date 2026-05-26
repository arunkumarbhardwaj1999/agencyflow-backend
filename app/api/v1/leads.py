from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_company, require_permission
from app.db.session import get_db
from app.models.lead import Lead
from app.schemas.common import MessageResponse
from app.schemas.lead import LeadCreate, LeadOut, LeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"])

LEAD_STATUSES = {"new", "contacted", "proposal", "won", "lost"}


@router.get("", response_model=list[LeadOut])
async def list_leads(
    status: str | None = None,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    q = select(Lead).where(Lead.company_id == current.company_id).order_by(Lead.created_at.desc())
    if status:
        q = q.where(Lead.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use: {', '.join(LEAD_STATUSES)}")
    lead = Lead(company_id=current.company_id, **body.model_dump())
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    return lead


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    for k, v in data.items():
        setattr(lead, k, v)
    await db.flush()
    await db.refresh(lead)
    return lead


@router.delete("/{lead_id}", response_model=MessageResponse)
async def delete_lead(
    lead_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    await db.delete(lead)
    return MessageResponse(message="Lead deleted")


async def _get_lead(db: AsyncSession, lead_id: UUID, company_id: UUID) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
