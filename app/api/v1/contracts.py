from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.contract_pdf import PdfContract, build_contract_pdf
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.email import _wrap, pdf_attachment, send_email
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.contract import Contract
from app.models.proposal import Proposal
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.contract import (
    CONTRACT_STATUSES,
    ContractCreate,
    ContractExpiryReminder,
    ContractOut,
    ContractSignRequest,
    ContractUpdate,
)

router = APIRouter(prefix="/contracts", tags=["contracts"])
settings = get_settings()


@router.get("", response_model=list[ContractOut])
async def list_contracts(
    client_id: UUID | None = None,
    proposal_id: UUID | None = None,
    status_filter: str | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(Contract).where(Contract.company_id == current.company_id)
    if client_id:
        q = q.where(Contract.client_id == client_id)
    if proposal_id:
        q = q.where(Contract.proposal_id == proposal_id)
    if status_filter:
        q = q.where(Contract.status == status_filter)
    q = q.order_by(Contract.updated_at.desc())
    result = await db.execute(q)
    contracts = list(result.scalars().all())
    out: list[ContractOut] = []
    for c in contracts:
        await _sync_expiry_status(db, c)
        out.append(await _contract_out(db, c))
    return out


@router.get("/expiring", response_model=list[ContractExpiryReminder])
async def list_expiring_contracts(
    days: int = Query(default=30, ge=1, le=365),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    cutoff = today + timedelta(days=days)
    result = await db.execute(
        select(Contract).where(
            Contract.company_id == current.company_id,
            Contract.status.in_(("signed", "active")),
            Contract.expires_at.is_not(None),
            Contract.expires_at <= cutoff,
            Contract.expires_at >= today,
            Contract.auto_renewal_reminder.is_(True),
        )
    )
    reminders: list[ContractExpiryReminder] = []
    for contract in result.scalars().all():
        client = await db.get(Client, contract.client_id)
        days_remaining = (contract.expires_at - today).days if contract.expires_at else 0
        reminders.append(
            ContractExpiryReminder(
                contract_id=contract.id,
                contract_number=contract.contract_number,
                title=contract.title,
                client_name=client.business_name if client else "Client",
                expires_at=contract.expires_at,
                days_remaining=days_remaining,
            )
        )
    reminders.sort(key=lambda r: r.expires_at)
    return reminders


@router.post("", response_model=ContractOut, status_code=status.HTTP_201_CREATED)
async def create_contract(
    body: ContractCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, body.client_id, current.company_id)
    if body.proposal_id:
        proposal = await _get_proposal(db, body.proposal_id, current.company_id)
        if proposal.status != "approved":
            raise HTTPException(status_code=400, detail="Proposal must be approved first")
        existing = await db.execute(
            select(Contract).where(
                Contract.proposal_id == body.proposal_id,
                Contract.company_id == current.company_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Contract already exists for this proposal")

    contract = Contract(
        company_id=current.company_id,
        client_id=client.id,
        proposal_id=body.proposal_id,
        created_by_id=current.id,
        contract_number=await _next_contract_number(db, current.company_id),
        title=body.title,
        project_value=body.project_value,
        services=body.services,
        body=body.body,
        status="draft",
        expires_at=body.expires_at,
        auto_renewal_reminder=body.auto_renewal_reminder,
        renewal_reminder_days=body.renewal_reminder_days,
    )
    db.add(contract)
    await db.flush()
    await realtime_manager.broadcast(
        current.company_id, "contract", f"Agreement created: {contract.title}"
    )
    return await _contract_out(db, contract)


@router.post("/from-proposal/{proposal_id}", response_model=ContractOut, status_code=status.HTTP_201_CREATED)
async def create_contract_from_proposal(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    if proposal.status != "approved":
        raise HTTPException(status_code=400, detail="Proposal must be approved before generating agreement")
    if not proposal.client_id:
        raise HTTPException(status_code=400, detail="Proposal must be linked to a client")

    existing = await db.execute(
        select(Contract).where(
            Contract.proposal_id == proposal_id,
            Contract.company_id == current.company_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Contract already exists for this proposal")

    client = await _get_client(db, proposal.client_id, current.company_id)
    company = await db.get(Company, current.company_id)
    agency = company.company_name if company else "AgencyFlow"
    body_text = _agreement_body_from_proposal(proposal, agency, client.business_name)

    contract = Contract(
        company_id=current.company_id,
        client_id=client.id,
        proposal_id=proposal.id,
        created_by_id=current.id,
        contract_number=await _next_contract_number(db, current.company_id),
        title=f"Service Agreement — {proposal.title}",
        project_value=float(proposal.project_value or 0),
        services=list(proposal.services or []),
        body=body_text,
        status="draft",
        auto_renewal_reminder=True,
        renewal_reminder_days=30,
    )
    db.add(contract)
    await db.flush()
    await realtime_manager.broadcast(
        current.company_id, "contract", f"Agreement generated from proposal: {proposal.title}"
    )
    return await _contract_out(db, contract)


@router.get("/{contract_id}", response_model=ContractOut)
async def get_contract(
    contract_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    await _sync_expiry_status(db, contract)
    return await _contract_out(db, contract)


@router.patch("/{contract_id}", response_model=ContractOut)
async def update_contract(
    contract_id: UUID,
    body: ContractUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in CONTRACT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    for k, v in data.items():
        setattr(contract, k, v)
    await db.flush()
    return await _contract_out(db, contract)


@router.delete("/{contract_id}", response_model=MessageResponse)
async def delete_contract(
    contract_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    await db.delete(contract)
    return MessageResponse(message="Contract deleted")


@router.get("/{contract_id}/pdf")
async def contract_pdf(
    contract_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    pdf_bytes = await _render_contract_pdf(db, contract)
    safe = contract.contract_number.replace('"', "")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


@router.post("/{contract_id}/send", response_model=MessageResponse)
async def send_contract(
    contract_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    client = await _get_client(db, contract.client_id, current.company_id)
    if not client.email:
        raise HTTPException(status_code=400, detail="Client has no email address")

    company = await db.get(Company, current.company_id)
    agency = company.company_name if company else "AgencyFlow"
    pdf_bytes = await _render_contract_pdf(db, contract)
    subject = f"Service Agreement: {contract.title}"
    text = (
        f"Hi {client.name},\n\n"
        f"Please review the attached service agreement ({contract.contract_number}) "
        f"for {contract.title}. Reply to confirm or use the signing link we will share.\n\n"
        f"Best regards,\n{agency}"
    )
    sent, err = await send_email(
        client.email,
        subject,
        _wrap(subject, text.replace("\n", "<br>")),
        attachments=[pdf_attachment(f"{contract.contract_number}.pdf", pdf_bytes)],
    )
    if not sent and settings.email_enabled:
        raise HTTPException(status_code=502, detail=err or "Email could not be sent")

    contract.status = "sent"
    contract.sent_at = datetime.now(UTC)
    await db.flush()
    mode = "sent" if settings.email_enabled else "logged (mock)"
    return MessageResponse(message=f"Agreement emailed to {client.email} ({mode})")


@router.post("/{contract_id}/sign", response_model=ContractOut)
async def sign_contract(
    contract_id: UUID,
    body: ContractSignRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    if not body.accept_terms:
        raise HTTPException(status_code=400, detail="Terms must be accepted to sign")

    contract = await _get_contract(db, contract_id, current.company_id)
    if contract.status not in ("sent", "draft"):
        raise HTTPException(status_code=400, detail="Contract cannot be signed in current status")

    now = datetime.now(UTC)
    today = date.today()
    contract.signer_name = body.signer_name.strip()
    contract.signer_email = body.signer_email.strip()
    contract.signed_at = now
    contract.starts_at = today
    contract.expires_at = contract.expires_at or (today + timedelta(days=365))
    contract.status = "active"
    await db.flush()

    await realtime_manager.broadcast(
        current.company_id,
        "contract",
        f"Agreement signed: {contract.title} by {contract.signer_name}",
    )
    return await _contract_out(db, contract)


@router.post("/{contract_id}/renew", response_model=ContractOut)
async def renew_contract(
    contract_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    contract = await _get_contract(db, contract_id, current.company_id)
    today = date.today()
    base = contract.expires_at if contract.expires_at and contract.expires_at >= today else today
    contract.expires_at = base + timedelta(days=365)
    contract.status = "active"
    await db.flush()
    await realtime_manager.broadcast(
        current.company_id, "contract", f"Agreement renewed: {contract.title}"
    )
    return await _contract_out(db, contract)


def _agreement_body_from_proposal(proposal: Proposal, agency: str, client_name: str) -> str:
    parts = [
        f"This Service Agreement is entered into between {agency} (\"Agency\") and "
        f"{client_name} (\"Client\") following approval of the related proposal.",
    ]
    if proposal.overview:
        parts.append(f"PROJECT OVERVIEW\n{proposal.overview}")
    if proposal.scope:
        parts.append(f"SCOPE OF WORK\n{proposal.scope}")
    if proposal.deliverables:
        parts.append(f"DELIVERABLES\n{proposal.deliverables}")
    if proposal.timeline:
        parts.append(f"TIMELINE\n{proposal.timeline}")
    if proposal.pricing:
        parts.append(f"COMMERCIAL TERMS\n{proposal.pricing}")
    if proposal.terms:
        parts.append(f"TERMS & CONDITIONS\n{proposal.terms}")
    else:
        parts.append(
            "TERMS & CONDITIONS\n"
            "1. Client agrees to provide timely feedback and content.\n"
            "2. Agency retains tools and frameworks; deliverables transfer on full payment.\n"
            "3. Either party may terminate with 30 days written notice.\n"
            "4. This agreement is governed by the laws of India."
        )
    parts.append(
        "SIGNATURE\n"
        "By signing electronically, both parties agree to the terms above."
    )
    return "\n\n".join(parts)


async def _next_contract_number(db: AsyncSession, company_id: UUID) -> str:
    year = date.today().year
    result = await db.execute(
        select(func.count()).select_from(Contract).where(Contract.company_id == company_id)
    )
    seq = result.scalar_one() + 1
    return f"AGR-{year}-{seq:04d}"


async def _sync_expiry_status(db: AsyncSession, contract: Contract) -> None:
    if contract.status in ("active", "signed") and contract.expires_at:
        if contract.expires_at < date.today():
            contract.status = "expired"
            await db.flush()


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _contract_out(db: AsyncSession, contract: Contract) -> ContractOut:
    client = await db.get(Client, contract.client_id)
    days_until = None
    renewal_due = False
    if contract.expires_at:
        days_until = (contract.expires_at - date.today()).days
        if contract.auto_renewal_reminder and 0 <= days_until <= contract.renewal_reminder_days:
            renewal_due = True
    return ContractOut(
        id=contract.id,
        company_id=contract.company_id,
        proposal_id=contract.proposal_id,
        client_id=contract.client_id,
        client_name=client.business_name if client else None,
        created_by_id=contract.created_by_id,
        created_by_name=await _creator_name(db, contract.created_by_id),
        renewed_from_id=contract.renewed_from_id,
        contract_number=contract.contract_number,
        title=contract.title,
        project_value=float(contract.project_value or 0),
        services=list(contract.services or []),
        body=contract.body,
        status=contract.status,
        signer_name=contract.signer_name,
        signer_email=contract.signer_email,
        signed_at=contract.signed_at,
        sent_at=contract.sent_at,
        starts_at=contract.starts_at,
        expires_at=contract.expires_at,
        auto_renewal_reminder=contract.auto_renewal_reminder,
        renewal_reminder_days=contract.renewal_reminder_days,
        days_until_expiry=days_until,
        renewal_due_soon=renewal_due,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


async def _render_contract_pdf(db: AsyncSession, contract: Contract) -> bytes:
    company = await db.get(Company, contract.company_id)
    client = await db.get(Client, contract.client_id)
    signed_date = contract.signed_at.date() if contract.signed_at else None
    return build_contract_pdf(
        PdfContract(
            contract_number=contract.contract_number,
            title=contract.title,
            agency_name=company.company_name if company else "AgencyFlow",
            client_name=client.business_name if client else "Client",
            project_value=Decimal(str(contract.project_value or 0)),
            services=list(contract.services or []),
            body=contract.body or "",
            signed_at=signed_date,
            signer_name=contract.signer_name,
            expires_at=contract.expires_at,
        )
    )


async def _get_contract(db: AsyncSession, contract_id: UUID, company_id: UUID) -> Contract:
    result = await db.execute(
        select(Contract).where(Contract.id == contract_id, Contract.company_id == company_id)
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


async def _get_client(db: AsyncSession, client_id: UUID, company_id: UUID) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.company_id == company_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _get_proposal(db: AsyncSession, proposal_id: UUID, company_id: UUID) -> Proposal:
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.company_id == company_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal
