from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_company
from app.db.session import get_db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.project import Project
from app.schemas.invoice import InvoiceOut
from app.schemas.project import ProjectOut

router = APIRouter(prefix="/portal", tags=["portal"])


async def _portal_client(db: AsyncSession, current: CurrentUser) -> Client:
    if current.role_name != "client":
        raise HTTPException(status_code=403, detail="Client portal access only")
    result = await db.execute(
        select(Client).where(
            Client.company_id == current.company_id,
            Client.email == current.user.email,
        )
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=404,
            detail="No client record for your email. Ask your agency to add you as a client contact.",
        )
    return client


@router.get("/projects", response_model=list[ProjectOut])
async def portal_projects(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from sqlalchemy.orm import selectinload

    from app.api.v1.projects import _project_out

    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.company_id == current.company_id, Project.client_id == client.id)
    )
    return [_project_out(p) for p in result.scalars().all()]


@router.get("/invoices", response_model=list[InvoiceOut])
async def portal_invoices(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from app.api.v1.invoices import _enrich

    result = await db.execute(
        select(Invoice)
        .where(Invoice.company_id == current.company_id, Invoice.client_id == client.id)
        .order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    return [await _enrich(db, inv) for inv in invoices]


@router.get("/me")
async def portal_me(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.role_name != "client":
        raise HTTPException(status_code=403, detail="Client portal only")
    client = await _portal_client(db, current)
    return {
        "client_id": str(client.id),
        "name": client.name,
        "business_name": client.business_name,
        "email": client.email,
    }
