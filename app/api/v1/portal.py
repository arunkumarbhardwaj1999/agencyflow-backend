from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, get_current_user, require_company
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.invoice import Invoice
from app.models.project import Project
from app.schemas.invoice import InvoiceOut
from app.schemas.portal import PortalMe, PortalSummary
from app.schemas.project import ProjectOut

router = APIRouter(prefix="/portal", tags=["portal"])

ACTIVE_PROJECT_STATUSES = ("planning", "active", "review")


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


@router.get("/me", response_model=PortalMe)
async def portal_me(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    company = await db.get(Company, current.company_id)
    return PortalMe(
        client_id=str(client.id),
        name=client.name,
        business_name=client.business_name,
        email=client.email,
        company_name=company.company_name if company else "Your agency",
    )


@router.get("/summary", response_model=PortalSummary)
async def portal_summary(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)

    projects = (
        await db.execute(
            select(Project.status).where(
                Project.company_id == current.company_id, Project.client_id == client.id
            )
        )
    ).scalars().all()
    active = sum(1 for s in projects if s in ACTIVE_PROJECT_STATUSES)
    completed = sum(1 for s in projects if s == "completed")

    invoices = (
        await db.execute(
            select(Invoice.total, Invoice.status).where(
                Invoice.company_id == current.company_id, Invoice.client_id == client.id
            )
        )
    ).all()
    total_invoiced = sum((Decimal(row[0]) for row in invoices), Decimal("0"))
    total_paid = sum((Decimal(row[0]) for row in invoices if row[1] == "paid"), Decimal("0"))
    outstanding = total_invoiced - total_paid

    return PortalSummary(
        active_projects=active,
        completed_projects=completed,
        total_projects=len(projects),
        invoice_count=len(invoices),
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        outstanding=outstanding,
    )


@router.get("/projects", response_model=list[ProjectOut])
async def portal_projects(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
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
    from app.api.v1.invoices import _to_out

    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.company_id == current.company_id, Invoice.client_id == client.id)
        .order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    return [_to_out(inv, client.business_name) for inv in invoices]


@router.get("/invoices/{invoice_id}/pdf")
async def portal_invoice_pdf(
    invoice_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from app.api.v1.invoices import pdf_response, render_invoice_pdf

    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(
            Invoice.id == invoice_id,
            Invoice.company_id == current.company_id,
            Invoice.client_id == client.id,
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    pdf_bytes = await render_invoice_pdf(db, invoice)
    return pdf_response(invoice.invoice_number, pdf_bytes)
