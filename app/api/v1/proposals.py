from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import AIError, draft_proposal_content
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.proposal_pdf import PdfProposal, build_proposal_pdf
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.contract import Contract
from app.models.deal import Deal
from app.models.lead import Lead
from app.models.proposal import Proposal
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.proposal import (
    PROPOSAL_STATUSES,
    PROPOSAL_TEMPLATES,
    ProposalAIDraftOut,
    ProposalAIDraftRequest,
    ProposalCreate,
    ProposalOut,
    ProposalTemplateOut,
    ProposalUpdate,
)

router = APIRouter(prefix="/proposals", tags=["proposals"])
settings = get_settings()

_TEMPLATE_MAP = {t["key"]: t for t in PROPOSAL_TEMPLATES}


@router.get("/templates", response_model=list[ProposalTemplateOut])
async def list_proposal_templates(current: CurrentUser = Depends(require_staff)):
    return [ProposalTemplateOut(**t) for t in PROPOSAL_TEMPLATES]


@router.get("", response_model=list[ProposalOut])
async def list_proposals(
    client_id: UUID | None = None,
    status_filter: str | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(Proposal).where(Proposal.company_id == current.company_id)
    if client_id:
        q = q.where(Proposal.client_id == client_id)
    if status_filter:
        q = q.where(Proposal.status == status_filter)
    q = q.order_by(Proposal.updated_at.desc())
    result = await db.execute(q)
    proposals = list(result.scalars().all())
    out: list[ProposalOut] = []
    for p in proposals:
        out.append(await _proposal_out(db, p))
    return out


@router.post("", response_model=ProposalOut, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    body: ProposalCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    if body.template_key not in _TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Invalid template")
    if body.client_id:
        await _get_client(db, body.client_id, current.company_id)
    if body.lead_id:
        await _get_lead(db, body.lead_id, current.company_id)
    if body.deal_id:
        await _get_deal(db, body.deal_id, current.company_id)

    services = body.services or list(_TEMPLATE_MAP[body.template_key]["default_services"])
    proposal = Proposal(
        company_id=current.company_id,
        client_id=body.client_id,
        lead_id=body.lead_id,
        deal_id=body.deal_id,
        created_by_id=current.id,
        template_key=body.template_key,
        title=body.title,
        project_value=body.project_value,
        services=services,
        overview=body.overview,
        timeline=body.timeline,
        deliverables=body.deliverables,
        scope=body.scope,
        pricing=body.pricing,
        terms=body.terms,
        conclusion=body.conclusion,
        status="draft",
    )
    db.add(proposal)
    await db.flush()
    await realtime_manager.broadcast(current.company_id, "proposal", f"Proposal created: {proposal.title}")
    return await _proposal_out(db, proposal)


@router.post("/ai-draft", response_model=ProposalAIDraftOut)
async def ai_draft_proposal(
    body: ProposalAIDraftRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, current.company_id)
    agency = company.company_name if company else "AgencyFlow"

    client_name = "Client"
    project_value = 0.0
    if body.client_id:
        client = await _get_client(db, body.client_id, current.company_id)
        client_name = client.business_name
    if body.lead_id:
        lead = await _get_lead(db, body.lead_id, current.company_id)
        client_name = lead.company_name or lead.name
        project_value = float(lead.value or 0)
    if body.deal_id:
        deal = await _get_deal(db, body.deal_id, current.company_id)
        client_name = deal.company_name or deal.title
        project_value = float(deal.value or 0)

    template = _TEMPLATE_MAP.get(body.template_key, _TEMPLATE_MAP["website"])
    try:
        draft = await draft_proposal_content(
            prompt=body.prompt,
            template_key=body.template_key,
            template_label=template["label"],
            client_name=client_name,
            project_value=project_value,
            services=list(template["default_services"]),
            agency_name=agency,
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    mode = "live" if settings.ai_enabled else "mock"
    return ProposalAIDraftOut(**draft, mode=mode)


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    return await _proposal_out(db, proposal)


@router.patch("/{proposal_id}", response_model=ProposalOut)
async def update_proposal(
    proposal_id: UUID,
    body: ProposalUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "template_key" in data and data["template_key"] not in _TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Invalid template")
    if "status" in data and data["status"] not in PROPOSAL_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if "client_id" in data and data["client_id"]:
        await _get_client(db, data["client_id"], current.company_id)
    for k, v in data.items():
        setattr(proposal, k, v)
    await db.flush()
    return await _proposal_out(db, proposal)


@router.delete("/{proposal_id}", response_model=MessageResponse)
async def delete_proposal(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    await db.delete(proposal)
    return MessageResponse(message="Proposal deleted")


@router.get("/{proposal_id}/pdf")
async def proposal_pdf(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    pdf_bytes = await _render_proposal_pdf(db, proposal)
    safe_name = proposal.title.replace('"', "'")[:80]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}.pdf"'},
    )


@router.post("/{proposal_id}/send", response_model=MessageResponse)
async def send_proposal(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    if not proposal.client_id:
        raise HTTPException(status_code=400, detail="Link a client before sending")
    client = await _get_client(db, proposal.client_id, current.company_id)
    if not client.email:
        raise HTTPException(status_code=400, detail="Client has no email address")

    company = await db.get(Company, current.company_id)
    agency = company.company_name if company else "AgencyFlow"
    pdf_bytes = await _render_proposal_pdf(db, proposal)
    subject = f"Proposal: {proposal.title}"
    body = (
        f"Hi {client.name},\n\n"
        f"Please find attached our proposal for {proposal.title}. "
        f"Project value: ₹{proposal.project_value:,.2f}.\n\n"
        f"Reply to this email if you'd like to discuss or approve.\n\n"
        f"Best regards,\n{agency}"
    )
    from app.core.email import pdf_attachment, send_email

    html_body = body.replace("\n", "<br>")
    from app.core.email import _wrap

    sent, err = await send_email(
        client.email,
        subject,
        _wrap(subject, html_body),
        attachments=[pdf_attachment(f"{proposal.title}.pdf", pdf_bytes)],
    )
    if not sent and settings.email_enabled:
        raise HTTPException(status_code=502, detail=err or "Email could not be sent")

    proposal.status = "sent"
    proposal.sent_at = datetime.now(UTC)
    await db.flush()
    msg = f"Proposal sent to {client.email}" if settings.email_enabled else "Proposal email logged (mock)"
    return MessageResponse(message=msg)


@router.post("/{proposal_id}/approve", response_model=ProposalOut)
async def approve_proposal(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await _get_proposal(db, proposal_id, current.company_id)
    proposal.status = "approved"
    proposal.approved_at = datetime.now(UTC)
    await db.flush()
    return await _proposal_out(db, proposal)


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _proposal_out(db: AsyncSession, proposal: Proposal) -> ProposalOut:
    client_name = None
    if proposal.client_id:
        client = await db.get(Client, proposal.client_id)
        if client:
            client_name = client.business_name
    template = _TEMPLATE_MAP.get(proposal.template_key, {"label": proposal.template_key})
    contract_id = None
    c_result = await db.execute(
        select(Contract.id).where(
            Contract.proposal_id == proposal.id,
            Contract.company_id == proposal.company_id,
        )
    )
    c_row = c_result.scalar_one_or_none()
    if c_row:
        contract_id = c_row
    return ProposalOut(
        id=proposal.id,
        company_id=proposal.company_id,
        client_id=proposal.client_id,
        lead_id=proposal.lead_id,
        deal_id=proposal.deal_id,
        created_by_id=proposal.created_by_id,
        created_by_name=await _creator_name(db, proposal.created_by_id),
        client_name=client_name,
        template_key=proposal.template_key,
        template_label=template["label"],
        title=proposal.title,
        project_value=float(proposal.project_value or 0),
        services=list(proposal.services or []),
        overview=proposal.overview,
        timeline=proposal.timeline,
        deliverables=proposal.deliverables,
        scope=proposal.scope,
        pricing=proposal.pricing,
        terms=proposal.terms,
        conclusion=proposal.conclusion,
        status=proposal.status,
        sent_at=proposal.sent_at,
        approved_at=proposal.approved_at,
        contract_id=contract_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


async def _render_proposal_pdf(db: AsyncSession, proposal: Proposal) -> bytes:
    company = await db.get(Company, proposal.company_id)
    agency = company.company_name if company else "AgencyFlow"
    client_name = "Client"
    if proposal.client_id:
        client = await db.get(Client, proposal.client_id)
        if client:
            client_name = client.business_name
    template = _TEMPLATE_MAP.get(proposal.template_key, {"label": proposal.template_key})
    sections = [
        ("Project Overview", proposal.overview or ""),
        ("Timeline", proposal.timeline or ""),
        ("Deliverables", proposal.deliverables or ""),
        ("Scope", proposal.scope or ""),
        ("Pricing", proposal.pricing or ""),
        ("Terms & Conditions", proposal.terms or ""),
        ("Conclusion", proposal.conclusion or ""),
    ]
    return build_proposal_pdf(
        PdfProposal(
            title=proposal.title,
            agency_name=agency,
            client_name=client_name,
            template_label=template["label"],
            project_value=Decimal(str(proposal.project_value or 0)),
            services=list(proposal.services or []),
            sections=sections,
        )
    )


async def _get_proposal(db: AsyncSession, proposal_id: UUID, company_id: UUID) -> Proposal:
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.company_id == company_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


async def _get_client(db: AsyncSession, client_id: UUID, company_id: UUID) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.company_id == company_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _get_lead(db: AsyncSession, lead_id: UUID, company_id: UUID) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


async def _get_deal(db: AsyncSession, deal_id: UUID, company_id: UUID) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id, Deal.company_id == company_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
