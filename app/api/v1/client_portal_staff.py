"""Staff endpoints for client portal: approvals, messages, milestones."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_permission, require_staff
from app.db.session import get_db
from app.models.client import Client
from app.models.document import Document
from app.models.portal import ClientApproval, ClientMessage, ProjectMilestone
from app.models.project import Project
from app.schemas.common import MessageResponse
from app.schemas.portal import (
    ApprovalCreate,
    MilestoneCreate,
    MilestoneUpdate,
    PortalApprovalOut,
    PortalMessageOut,
    PortalMilestoneOut,
    StaffClientMessageCreate,
)

router = APIRouter(prefix="/client-portal", tags=["client-portal-staff"])

KIND_LABELS = {
    "design": "Design",
    "video": "Video",
    "document": "Document",
    "deliverable": "Deliverable",
}


@router.get("/approvals", response_model=list[PortalApprovalOut])
async def list_approvals(
    client_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(ClientApproval)
        .where(ClientApproval.company_id == current.company_id)
        .order_by(ClientApproval.created_at.desc())
    )
    if client_id:
        q = q.where(ClientApproval.client_id == client_id)
    if status_filter:
        q = q.where(ClientApproval.status == status_filter)
    approvals = list((await db.execute(q)).scalars().all())
    return [await _approval_out(db, a) for a in approvals]


@router.post("/approvals", response_model=PortalApprovalOut, status_code=status.HTTP_201_CREATED)
async def create_approval(
    body: ApprovalCreate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    client = await db.execute(
        select(Client).where(Client.id == body.client_id, Client.company_id == current.company_id)
    )
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")
    if body.project_id:
        project = await db.execute(
            select(Project).where(
                Project.id == body.project_id,
                Project.company_id == current.company_id,
                Project.client_id == body.client_id,
            )
        )
        if not project.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found for this client")
    if body.document_id:
        doc = await db.get(Document, body.document_id)
        if not doc or doc.company_id != current.company_id:
            raise HTTPException(status_code=404, detail="Document not found")

    approval = ClientApproval(
        company_id=current.company_id,
        client_id=body.client_id,
        project_id=body.project_id,
        document_id=body.document_id,
        title=body.title,
        description=body.description,
        kind=body.kind,
        status="pending",
        created_by_id=current.id,
    )
    db.add(approval)
    await db.flush()
    return await _approval_out(db, approval)


@router.delete("/approvals/{approval_id}", response_model=MessageResponse)
async def delete_approval(
    approval_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientApproval).where(
            ClientApproval.id == approval_id,
            ClientApproval.company_id == current.company_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    await db.delete(approval)
    return MessageResponse(message="Approval deleted")


@router.get("/messages", response_model=list[PortalMessageOut])
async def list_client_messages(
    client_id: UUID = Query(...),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    client = await db.execute(
        select(Client).where(Client.id == client_id, Client.company_id == current.company_id)
    )
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")
    from app.api.v1.portal import _messages_for_client

    return await _messages_for_client(db, current.company_id, client_id)


@router.post("/messages", response_model=PortalMessageOut, status_code=status.HTTP_201_CREATED)
async def staff_send_client_message(
    body: StaffClientMessageCreate,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    client = await db.execute(
        select(Client).where(Client.id == body.client_id, Client.company_id == current.company_id)
    )
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")
    if body.project_id:
        project = await db.execute(
            select(Project).where(
                Project.id == body.project_id,
                Project.company_id == current.company_id,
                Project.client_id == body.client_id,
            )
        )
        if not project.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found")

    msg = ClientMessage(
        company_id=current.company_id,
        client_id=body.client_id,
        project_id=body.project_id,
        sender_user_id=current.id,
        sender_side="staff",
        body=body.body.strip(),
        is_read=False,
    )
    db.add(msg)
    await db.flush()
    from app.api.v1.portal import _messages_for_client

    outs = await _messages_for_client(db, current.company_id, body.client_id)
    return next(m for m in outs if m.id == msg.id)


@router.get("/projects/{project_id}/milestones", response_model=list[PortalMilestoneOut])
async def list_milestones(
    project_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, project_id, current.company_id)
    return await _milestones(db, current.company_id, project_id)


@router.post(
    "/projects/{project_id}/milestones",
    response_model=PortalMilestoneOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
    project_id: UUID,
    body: MilestoneCreate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, project_id, current.company_id)
    if body.status not in {"pending", "completed"}:
        raise HTTPException(status_code=400, detail="Invalid milestone status")
    m = ProjectMilestone(
        company_id=current.company_id,
        project_id=project_id,
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        status=body.status,
        sort_order=body.sort_order,
    )
    db.add(m)
    await db.flush()
    return PortalMilestoneOut(
        id=m.id,
        project_id=m.project_id,
        title=m.title,
        description=m.description,
        due_date=m.due_date,
        status=m.status,
        sort_order=m.sort_order,
    )


@router.patch("/milestones/{milestone_id}", response_model=PortalMilestoneOut)
async def update_milestone(
    milestone_id: UUID,
    body: MilestoneUpdate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.company_id == current.company_id,
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in {"pending", "completed"}:
        raise HTTPException(status_code=400, detail="Invalid milestone status")
    for k, v in data.items():
        setattr(m, k, v)
    await db.flush()
    return PortalMilestoneOut(
        id=m.id,
        project_id=m.project_id,
        title=m.title,
        description=m.description,
        due_date=m.due_date,
        status=m.status,
        sort_order=m.sort_order,
    )


@router.delete("/milestones/{milestone_id}", response_model=MessageResponse)
async def delete_milestone(
    milestone_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.company_id == current.company_id,
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    await db.delete(m)
    return MessageResponse(message="Milestone deleted")


async def _get_project(db: AsyncSession, project_id: UUID, company_id: UUID) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.company_id == company_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _milestones(db: AsyncSession, company_id: UUID, project_id: UUID) -> list[PortalMilestoneOut]:
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


async def _approval_out(db: AsyncSession, a: ClientApproval) -> PortalApprovalOut:
    project_title = None
    if a.project_id:
        p = await db.get(Project, a.project_id)
        project_title = p.title if p else None
    doc_name = None
    if a.document_id:
        d = await db.get(Document, a.document_id)
        doc_name = d.filename if d else None
    return PortalApprovalOut(
        id=a.id,
        project_id=a.project_id,
        project_title=project_title,
        document_id=a.document_id,
        document_filename=doc_name,
        title=a.title,
        description=a.description,
        kind=a.kind,
        kind_label=KIND_LABELS.get(a.kind, a.kind.title()),
        status=a.status,
        client_comment=a.client_comment,
        decided_at=a.decided_at,
        created_at=a.created_at,
    )
