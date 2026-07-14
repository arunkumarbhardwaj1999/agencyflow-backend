from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.document_folders import folder_label
from app.core.deps import CurrentUser, get_current_user, require_company
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.contract import Contract
from app.models.document import Document
from app.models.invoice import Invoice
from app.models.portal import ClientApproval, ClientMessage, ProjectMilestone
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.task import Task
from app.models.user import User
from app.schemas.invoice import InvoiceOut
from app.schemas.portal import (
    PortalActivityItem,
    PortalApprovalDecision,
    PortalApprovalOut,
    PortalFileOut,
    PortalMe,
    PortalMessageCreate,
    PortalMessageOut,
    PortalMilestoneOut,
    PortalProjectDetail,
    PortalSummary,
    PortalTaskOut,
)
from app.schemas.project import ProjectOut

router = APIRouter(prefix="/portal", tags=["portal"])

ACTIVE_PROJECT_STATUSES = ("planning", "active", "review")
PORTAL_FILE_FOLDERS = {"proposals", "agreements", "deliverables", "images", "invoices", "others"}
APPROVAL_KIND_LABELS = {
    "design": "Design",
    "video": "Video",
    "document": "Document",
    "deliverable": "Deliverable",
}


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


async def _client_project_ids(db: AsyncSession, company_id: UUID, client_id: UUID) -> set[UUID]:
    result = await db.execute(
        select(Project.id).where(Project.company_id == company_id, Project.client_id == client_id)
    )
    return set(result.scalars().all())


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
    from app.api.v1.projects import _project_out

    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.company_id == current.company_id, Project.client_id == client.id)
    )
    projects = list(result.scalars().all())
    outs = [_project_out(p) for p in projects]
    active = sum(1 for p in outs if p.status in ACTIVE_PROJECT_STATUSES)
    completed = sum(1 for p in outs if p.status == "completed")
    avg_progress = int(sum(p.progress_percent for p in outs) / len(outs)) if outs else 0

    invoices = (
        await db.execute(
            select(Invoice.total, Invoice.status).where(
                Invoice.company_id == current.company_id, Invoice.client_id == client.id
            )
        )
    ).all()
    total_invoiced = sum((Decimal(row[0]) for row in invoices), Decimal("0"))
    total_paid = sum((Decimal(row[0]) for row in invoices if row[1] == "paid"), Decimal("0"))
    unpaid_count = sum(1 for row in invoices if row[1] != "paid")

    pending = await db.execute(
        select(func.count())
        .select_from(ClientApproval)
        .where(
            ClientApproval.company_id == current.company_id,
            ClientApproval.client_id == client.id,
            ClientApproval.status == "pending",
        )
    )

    return PortalSummary(
        active_projects=active,
        completed_projects=completed,
        total_projects=len(outs),
        avg_progress_percent=avg_progress,
        pending_approvals=int(pending.scalar_one() or 0),
        invoice_count=len(invoices),
        unpaid_invoice_count=unpaid_count,
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        outstanding=total_invoiced - total_paid,
    )


@router.get("/activity", response_model=list[PortalActivityItem])
async def portal_activity(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    items: list[PortalActivityItem] = []

    invoices = (
        await db.execute(
            select(Invoice)
            .where(Invoice.company_id == current.company_id, Invoice.client_id == client.id)
            .order_by(Invoice.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    for inv in invoices:
        items.append(
            PortalActivityItem(
                id=f"invoice-{inv.id}",
                type="invoice",
                message=f"Invoice {inv.invoice_number} · {inv.status}",
                created_at=inv.created_at,
            )
        )

    approvals = (
        await db.execute(
            select(ClientApproval)
            .where(
                ClientApproval.company_id == current.company_id,
                ClientApproval.client_id == client.id,
            )
            .order_by(ClientApproval.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    for a in approvals:
        items.append(
            PortalActivityItem(
                id=f"approval-{a.id}",
                type="approval",
                message=f"Approval “{a.title}” · {a.status}",
                created_at=a.created_at,
            )
        )

    msgs = (
        await db.execute(
            select(ClientMessage)
            .where(
                ClientMessage.company_id == current.company_id,
                ClientMessage.client_id == client.id,
            )
            .order_by(ClientMessage.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    for m in msgs:
        side = "You" if m.sender_side == "client" else "Agency"
        preview = m.body[:80] + ("…" if len(m.body) > 80 else "")
        items.append(
            PortalActivityItem(
                id=f"message-{m.id}",
                type="message",
                message=f"{side}: {preview}",
                created_at=m.created_at,
            )
        )

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items[:15]


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
        .order_by(Project.created_at.desc())
    )
    return [_project_out(p) for p in result.scalars().all()]


@router.get("/projects/{project_id}", response_model=PortalProjectDetail)
async def portal_project_detail(
    project_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from app.api.v1.projects import _project_out

    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(
            Project.id == project_id,
            Project.company_id == current.company_id,
            Project.client_id == client.id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    out = _project_out(project)

    milestones = await _milestones_for_project(db, current.company_id, project.id)
    tasks = [
        PortalTaskOut(
            id=t.id,
            project_id=t.project_id,
            project_title=project.title,
            title=t.title,
            description=t.description,
            status=t.status,
            priority=t.priority,
            due_date=t.due_date,
            created_at=t.created_at,
        )
        for t in (project.tasks or [])
    ]
    files = await _files_for_client(db, current.company_id, client.id, project_id=project.id)
    approvals = await _approvals_for_client(db, current.company_id, client.id, project_id=project.id)

    return PortalProjectDetail(
        id=out.id,
        title=out.title,
        description=out.description,
        status=out.status,
        start_date=out.start_date,
        end_date=out.end_date,
        task_total=out.task_total,
        task_done=out.task_done,
        progress_percent=out.progress_percent,
        milestones=milestones,
        tasks=tasks,
        files=files,
        approvals=approvals,
    )


@router.get("/tasks", response_model=list[PortalTaskOut])
async def portal_tasks(
    project_id: UUID | None = None,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    project_ids = await _client_project_ids(db, current.company_id, client.id)
    if not project_ids:
        return []
    q = (
        select(Task, Project.title)
        .join(Project, Project.id == Task.project_id)
        .where(Task.company_id == current.company_id, Task.project_id.in_(project_ids))
        .order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
    )
    if project_id:
        if project_id not in project_ids:
            raise HTTPException(status_code=403, detail="Not your project")
        q = q.where(Task.project_id == project_id)
    rows = (await db.execute(q)).all()
    return [
        PortalTaskOut(
            id=t.id,
            project_id=t.project_id,
            project_title=title,
            title=t.title,
            description=t.description,
            status=t.status,
            priority=t.priority,
            due_date=t.due_date,
            created_at=t.created_at,
        )
        for t, title in rows
    ]


@router.get("/files", response_model=list[PortalFileOut])
async def portal_files(
    project_id: UUID | None = None,
    folder: str | None = None,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    return await _files_for_client(
        db, current.company_id, client.id, project_id=project_id, folder=folder
    )


@router.get("/files/{file_id}/download")
async def portal_file_download(
    file_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    doc = await _get_accessible_document(db, current.company_id, client.id, file_id)
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.get("/proposals/{proposal_id}/pdf")
async def portal_proposal_pdf(
    proposal_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from app.api.v1.proposals import _render_proposal_pdf

    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.company_id == current.company_id,
            Proposal.client_id == client.id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    pdf_bytes = await _render_proposal_pdf(db, proposal)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in proposal.title)[:80]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


@router.get("/contracts/{contract_id}/pdf")
async def portal_contract_pdf(
    contract_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    from app.api.v1.contracts import _render_contract_pdf

    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.company_id == current.company_id,
            Contract.client_id == client.id,
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Agreement not found")
    pdf_bytes = await _render_contract_pdf(db, contract)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in contract.contract_number)[:80]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


@router.get("/approvals", response_model=list[PortalApprovalOut])
async def portal_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    return await _approvals_for_client(
        db, current.company_id, client.id, status_filter=status_filter
    )


@router.post("/approvals/{approval_id}/decide", response_model=PortalApprovalOut)
async def portal_decide_approval(
    approval_id: UUID,
    body: PortalApprovalDecision,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    result = await db.execute(
        select(ClientApproval).where(
            ClientApproval.id == approval_id,
            ClientApproval.company_id == current.company_id,
            ClientApproval.client_id == client.id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    approval.status = body.status
    approval.client_comment = body.client_comment
    approval.decided_at = datetime.now(UTC)
    await db.flush()
    outs = await _approvals_for_client(db, current.company_id, client.id)
    return next(a for a in outs if a.id == approval.id)


@router.get("/messages", response_model=list[PortalMessageOut])
async def portal_messages(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    return await _messages_for_client(db, current.company_id, client.id)


@router.post("/messages", response_model=PortalMessageOut, status_code=201)
async def portal_send_message(
    body: PortalMessageCreate,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _portal_client(db, current)
    if body.project_id:
        ids = await _client_project_ids(db, current.company_id, client.id)
        if body.project_id not in ids:
            raise HTTPException(status_code=403, detail="Not your project")
    msg = ClientMessage(
        company_id=current.company_id,
        client_id=client.id,
        project_id=body.project_id,
        sender_user_id=current.id,
        sender_side="client",
        body=body.body.strip(),
        is_read=False,
    )
    db.add(msg)
    await db.flush()
    outs = await _messages_for_client(db, current.company_id, client.id)
    return next(m for m in outs if m.id == msg.id)


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


async def _milestones_for_project(
    db: AsyncSession, company_id: UUID, project_id: UUID
) -> list[PortalMilestoneOut]:
    result = await db.execute(
        select(ProjectMilestone)
        .where(
            ProjectMilestone.company_id == company_id,
            ProjectMilestone.project_id == project_id,
        )
        .order_by(ProjectMilestone.sort_order.asc(), ProjectMilestone.created_at.asc())
    )
    return [
        PortalMilestoneOut(
            id=m.id,
            project_id=m.project_id,
            title=m.title,
            description=m.description,
            due_date=m.due_date,
            status=m.status,
            sort_order=m.sort_order,
        )
        for m in result.scalars().all()
    ]


async def _files_for_client(
    db: AsyncSession,
    company_id: UUID,
    client_id: UUID,
    project_id: UUID | None = None,
    folder: str | None = None,
) -> list[PortalFileOut]:
    project_ids = await _client_project_ids(db, company_id, client_id)
    conds = [Document.client_id == client_id]
    if project_ids:
        conds.append(Document.project_id.in_(project_ids))

    q = (
        select(Document)
        .where(
            Document.company_id == company_id,
            Document.kind.in_(("document", "client_document")),
            or_(*conds),
            Document.folder.in_(PORTAL_FILE_FOLDERS),
        )
        .order_by(Document.created_at.desc())
    )
    if project_id:
        if project_id not in project_ids:
            raise HTTPException(status_code=403, detail="Not your project")
        q = q.where(Document.project_id == project_id)
    if folder:
        q = q.where(Document.folder == folder)

    docs = list((await db.execute(q)).scalars().all())
    title_map: dict[UUID, str] = {}
    if project_ids:
        rows = await db.execute(select(Project.id, Project.title).where(Project.id.in_(project_ids)))
        title_map = {pid: title for pid, title in rows.all()}

    return [
        PortalFileOut(
            id=d.id,
            project_id=d.project_id,
            project_title=title_map.get(d.project_id) if d.project_id else None,
            filename=d.filename,
            content_type=d.content_type,
            size=d.size,
            folder=d.folder,
            folder_label=folder_label(d.folder),
            kind=d.kind,
            source="document",
            created_at=d.created_at,
        )
        for d in docs
    ]


async def _get_accessible_document(
    db: AsyncSession, company_id: UUID, client_id: UUID, doc_id: UUID
) -> Document:
    files = await _files_for_client(db, company_id, client_id)
    if not any(f.id == doc_id for f in files):
        raise HTTPException(status_code=404, detail="File not found")
    doc = await db.get(Document, doc_id)
    if not doc or doc.company_id != company_id:
        raise HTTPException(status_code=404, detail="File not found")
    return doc


async def _approvals_for_client(
    db: AsyncSession,
    company_id: UUID,
    client_id: UUID,
    project_id: UUID | None = None,
    status_filter: str | None = None,
) -> list[PortalApprovalOut]:
    q = (
        select(ClientApproval)
        .where(
            ClientApproval.company_id == company_id,
            ClientApproval.client_id == client_id,
        )
        .order_by(ClientApproval.created_at.desc())
    )
    if project_id:
        q = q.where(ClientApproval.project_id == project_id)
    if status_filter:
        q = q.where(ClientApproval.status == status_filter)
    approvals = list((await db.execute(q)).scalars().all())

    project_ids = {a.project_id for a in approvals if a.project_id}
    title_map: dict[UUID, str] = {}
    if project_ids:
        rows = await db.execute(select(Project.id, Project.title).where(Project.id.in_(project_ids)))
        title_map = {pid: title for pid, title in rows.all()}

    doc_ids = {a.document_id for a in approvals if a.document_id}
    doc_map: dict[UUID, str] = {}
    if doc_ids:
        rows = await db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids)))
        doc_map = {did: name for did, name in rows.all()}

    return [
        PortalApprovalOut(
            id=a.id,
            project_id=a.project_id,
            project_title=title_map.get(a.project_id) if a.project_id else None,
            document_id=a.document_id,
            document_filename=doc_map.get(a.document_id) if a.document_id else None,
            title=a.title,
            description=a.description,
            kind=a.kind,
            kind_label=APPROVAL_KIND_LABELS.get(a.kind, a.kind.title()),
            status=a.status,
            client_comment=a.client_comment,
            decided_at=a.decided_at,
            created_at=a.created_at,
        )
        for a in approvals
    ]


async def _messages_for_client(
    db: AsyncSession, company_id: UUID, client_id: UUID
) -> list[PortalMessageOut]:
    result = await db.execute(
        select(ClientMessage)
        .where(
            ClientMessage.company_id == company_id,
            ClientMessage.client_id == client_id,
        )
        .order_by(ClientMessage.created_at.asc())
    )
    messages = list(result.scalars().all())
    user_ids = {m.sender_user_id for m in messages if m.sender_user_id}
    name_map: dict[UUID, str] = {}
    if user_ids:
        users = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in users.scalars().all():
            name_map[u.id] = f"{u.first_name} {u.last_name or ''}".strip()

    project_ids = {m.project_id for m in messages if m.project_id}
    title_map: dict[UUID, str] = {}
    if project_ids:
        rows = await db.execute(select(Project.id, Project.title).where(Project.id.in_(project_ids)))
        title_map = {pid: title for pid, title in rows.all()}

    return [
        PortalMessageOut(
            id=m.id,
            project_id=m.project_id,
            project_title=title_map.get(m.project_id) if m.project_id else None,
            sender_side=m.sender_side,
            sender_name=name_map.get(m.sender_user_id) if m.sender_user_id else None,
            body=m.body,
            is_read=m.is_read,
            created_at=m.created_at,
        )
        for m in messages
    ]
