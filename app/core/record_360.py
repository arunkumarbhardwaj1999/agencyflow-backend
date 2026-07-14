"""360° record view — aggregate all related data for Lead, Deal, Client, Project."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.communication_service import fetch_inbox_items
from app.core.deal_insights import compute_deal_insights
from app.models.client import Client
from app.models.communication import InternalComment
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_email import DealEmail
from app.models.deal_note import DealNote
from app.models.deal_timeline import DealTimeline
from app.models.document import Document
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_email import LeadEmail
from app.models.lead_note import LeadNote
from app.models.lead_timeline import LeadTimeline
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.communication import InboxItemOut
from app.core.deal_timeline import stage_label
from app.schemas.deal import DealOut
from app.schemas.deal_activity import (
    DEAL_ACTIVITY_LABELS,
    DealActivitiesGrouped,
    DealActivityOut,
    DealNoteOut,
)
from app.schemas.document import DealAttachmentOut, LeadAttachmentOut
from app.schemas.lead import LeadOut
from app.schemas.lead_activity import (
    ACTIVITY_LABELS,
    LeadActivitiesGrouped,
    LeadActivityOut,
)
from app.schemas.lead_note import LeadNoteOut
from app.schemas.deal_timeline import DealTimelineOut
from app.schemas.lead_timeline import LeadTimelineOut
from app.schemas.record_360 import (
    Record360Insights,
    Record360Related,
    Record360View,
    RelatedClientBrief,
    RelatedDealBrief,
    RelatedInvoiceBrief,
    RelatedLeadBrief,
    RelatedProjectBrief,
)

ENTITY_TYPES = frozenset({"lead", "deal", "client", "project"})
MEETING_TYPES = frozenset({"meeting", "demo"})


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _lead_out(db: AsyncSession, lead: Lead) -> LeadOut:
    return LeadOut.model_validate(lead)


async def _deal_out(db: AsyncSession, deal: Deal) -> DealOut:
    return DealOut(
        id=deal.id,
        company_id=deal.company_id,
        lead_id=deal.lead_id,
        client_id=deal.client_id,
        assigned_user_id=deal.assigned_user_id,
        assigned_to_name=await _creator_name(db, deal.assigned_user_id),
        title=deal.title,
        contact_name=deal.contact_name,
        contact_email=deal.contact_email,
        contact_phone=deal.contact_phone,
        company_name=deal.company_name,
        value=deal.value,
        probability=deal.probability,
        expected_close_date=deal.expected_close_date,
        status=deal.status,
        status_label=stage_label(deal.status),
        kanban_position=deal.kanban_position,
        source=deal.source,
        notes=deal.notes,
        lost_reason=deal.lost_reason,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


async def _lead_timeline(db: AsyncSession, lead_id: UUID, company_id: UUID) -> list[LeadTimelineOut]:
    result = await db.execute(
        select(LeadTimeline)
        .where(LeadTimeline.lead_id == lead_id, LeadTimeline.company_id == company_id)
        .order_by(LeadTimeline.created_at.desc())
    )
    out: list[LeadTimelineOut] = []
    for entry in result.scalars().all():
        out.append(
            LeadTimelineOut(
                id=entry.id,
                lead_id=entry.lead_id,
                event_type=entry.event_type,
                description=entry.description,
                created_by_id=entry.created_by_id,
                created_by_name=await _creator_name(db, entry.created_by_id),
                metadata=entry.meta,
                created_at=entry.created_at,
            )
        )
    return out


async def _deal_timeline(db: AsyncSession, deal_id: UUID, company_id: UUID) -> list[DealTimelineOut]:
    result = await db.execute(
        select(DealTimeline)
        .where(DealTimeline.deal_id == deal_id, DealTimeline.company_id == company_id)
        .order_by(DealTimeline.created_at.desc())
    )
    out: list[DealTimelineOut] = []
    for entry in result.scalars().all():
        out.append(
            DealTimelineOut(
                id=entry.id,
                deal_id=entry.deal_id,
                event_type=entry.event_type,
                description=entry.description,
                created_by_id=entry.created_by_id,
                created_by_name=await _creator_name(db, entry.created_by_id),
                metadata=entry.meta,
                created_at=entry.created_at,
            )
        )
    return out


async def _lead_activities(db: AsyncSession, lead_id: UUID, company_id: UUID) -> LeadActivitiesGrouped:
    result = await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id, LeadActivity.company_id == company_id)
        .order_by(LeadActivity.created_at.desc())
    )
    activities = list(result.scalars().all())
    upcoming = [a for a in activities if not a.is_completed]
    completed = [a for a in activities if a.is_completed]

    async def _out(a: LeadActivity) -> LeadActivityOut:
        label = ACTIVITY_LABELS.get(a.activity_type, a.activity_type)
        return LeadActivityOut(
            id=a.id,
            lead_id=a.lead_id,
            activity_type=a.activity_type,
            activity_label=label,
            title=a.title,
            notes=a.notes,
            scheduled_at=a.scheduled_at,
            completed_at=a.completed_at,
            is_completed=a.is_completed,
            assigned_to_id=a.assigned_to_id,
            assigned_to_name=await _creator_name(db, a.assigned_to_id),
            created_by_id=a.created_by_id,
            created_by_name=await _creator_name(db, a.created_by_id),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )

    return LeadActivitiesGrouped(
        upcoming=[await _out(a) for a in upcoming],
        completed=[await _out(a) for a in completed],
    )


async def _deal_activities(db: AsyncSession, deal_id: UUID, company_id: UUID) -> DealActivitiesGrouped:
    result = await db.execute(
        select(DealActivity)
        .where(DealActivity.deal_id == deal_id, DealActivity.company_id == company_id)
        .order_by(DealActivity.created_at.desc())
    )
    activities = list(result.scalars().all())
    upcoming = [a for a in activities if not a.is_completed]
    completed = [a for a in activities if a.is_completed]

    async def _out(a: DealActivity) -> DealActivityOut:
        label = DEAL_ACTIVITY_LABELS.get(a.activity_type, a.activity_type)
        return DealActivityOut(
            id=a.id,
            deal_id=a.deal_id,
            activity_type=a.activity_type,
            activity_label=label,
            title=a.title,
            notes=a.notes,
            scheduled_at=a.scheduled_at,
            completed_at=a.completed_at,
            is_completed=a.is_completed,
            assigned_to_id=a.assigned_to_id,
            assigned_to_name=await _creator_name(db, a.assigned_to_id),
            created_by_id=a.created_by_id,
            created_by_name=await _creator_name(db, a.created_by_id),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )

    return DealActivitiesGrouped(
        upcoming=[await _out(a) for a in upcoming],
        completed=[await _out(a) for a in completed],
    )


def _meetings_from_activities(activities: LeadActivitiesGrouped | DealActivitiesGrouped) -> list:
    meetings = []
    for group in (activities.upcoming, activities.completed):
        for act in group:
            if act.activity_type in MEETING_TYPES:
                meetings.append(act)
    return meetings


async def _lead_attachments(db: AsyncSession, lead_id: UUID, company_id: UUID) -> list[LeadAttachmentOut]:
    from app.api.v1.leads import _attachment_out

    result = await db.execute(
        select(Document).where(
            Document.lead_id == lead_id,
            Document.company_id == company_id,
            Document.kind == "lead_attachment",
        )
    )
    return [await _attachment_out(db, d) for d in result.scalars().all()]


async def _deal_attachments(db: AsyncSession, deal_id: UUID, company_id: UUID) -> list[DealAttachmentOut]:
    from app.api.v1.deals import _attachment_out

    result = await db.execute(
        select(Document).where(
            Document.deal_id == deal_id,
            Document.company_id == company_id,
            Document.kind.in_(("deal_attachment", "deal_proposal")),
        )
    )
    return [await _attachment_out(db, d) for d in result.scalars().all()]


async def _client_attachments(db: AsyncSession, client_id: UUID, company_id: UUID) -> list:
    from app.api.v1.clients import _client_document_out

    result = await db.execute(
        select(Document).where(
            Document.client_id == client_id,
            Document.company_id == company_id,
            Document.kind == "client_document",
        ).order_by(Document.folder.asc(), Document.created_at.desc())
    )
    return [await _client_document_out(db, d) for d in result.scalars().all()]


async def _lead_emails(db: AsyncSession, lead_id: UUID, company_id: UUID) -> list[dict]:
    result = await db.execute(
        select(LeadEmail)
        .where(LeadEmail.lead_id == lead_id, LeadEmail.company_id == company_id)
        .order_by(LeadEmail.sent_at.desc())
    )
    return [
        {
            "id": str(e.id),
            "subject": e.subject,
            "body": e.body,
            "to_email": e.to_email,
            "delivery_status": e.delivery_status,
            "open_status": e.open_status,
            "sent_at": e.sent_at.isoformat(),
        }
        for e in result.scalars().all()
    ]


async def _deal_emails(db: AsyncSession, deal_id: UUID, company_id: UUID) -> list[dict]:
    result = await db.execute(
        select(DealEmail)
        .where(DealEmail.deal_id == deal_id, DealEmail.company_id == company_id)
        .order_by(DealEmail.sent_at.desc())
    )
    return [
        {
            "id": str(e.id),
            "subject": e.subject,
            "body": e.body,
            "to_email": e.to_email,
            "delivery_status": e.delivery_status,
            "open_status": e.open_status,
            "sent_at": e.sent_at.isoformat(),
        }
        for e in result.scalars().all()
    ]


async def _messaging_for_entity(
    db: AsyncSession,
    company_id: UUID,
    user_id: UUID,
    *,
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    client_id: UUID | None = None,
) -> list[InboxItemOut]:
    items = await fetch_inbox_items(db, company_id, user_id, channel="messaging", limit=50)
    filtered = []
    for item in items:
        if lead_id and item.lead_id == lead_id:
            filtered.append(item)
        elif deal_id and item.deal_id == deal_id:
            filtered.append(item)
        elif client_id and item.client_id == client_id:
            filtered.append(item)
    return filtered


async def _internal_comments(
    db: AsyncSession, company_id: UUID, **filters
) -> list[dict]:
    q = select(InternalComment).where(InternalComment.company_id == company_id)
    for key, val in filters.items():
        if val:
            q = q.where(getattr(InternalComment, key) == val)
    result = await db.execute(q.order_by(InternalComment.created_at.desc()))
    out = []
    for c in result.scalars().all():
        out.append(
            {
                "id": str(c.id),
                "body": c.body,
                "author_name": await _creator_name(db, c.author_id),
                "created_at": c.created_at.isoformat(),
            }
        )
    return out


def _lead_insights(lead: Lead, activities: LeadActivitiesGrouped) -> Record360Insights:
    score = 30
    if lead.status == "proposal":
        score = 55
    elif lead.status == "contacted":
        score = 40
    elif lead.status == "won":
        score = 100
    elif lead.status == "lost":
        score = 0

    if lead.next_followup and lead.next_followup.date() <= date.today():
        score += 10
    if activities.upcoming:
        score += 5

    recs: list[str] = []
    if lead.next_followup and lead.next_followup.date() <= date.today():
        recs.append("Follow-up is due — reach out today.")
    if lead.status == "new":
        recs.append("Qualify the lead with a discovery call.")
    if not lead.email:
        recs.append("Add an email address to enable outreach.")

    confidence = "High" if score >= 70 else "Medium" if score >= 40 else "Low"
    return Record360Insights(
        score=score,
        confidence=confidence,
        summary=f"Lead in {lead.status} stage with {len(activities.upcoming)} upcoming activity(ies).",
        recommendations=recs[:3],
    )


async def build_lead_360(
    db: AsyncSession, company_id: UUID, user_id: UUID, lead_id: UUID
) -> Record360View:
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    notes_result = await db.execute(
        select(LeadNote).where(LeadNote.lead_id == lead_id).order_by(LeadNote.created_at.desc())
    )
    notes = []
    for n in notes_result.scalars().all():
        notes.append(
            LeadNoteOut(
                id=n.id,
                lead_id=n.lead_id,
                content=n.content,
                created_by_id=n.created_by_id,
                created_by_name=await _creator_name(db, n.created_by_id),
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
        )

    activities = await _lead_activities(db, lead_id, company_id)
    deals_result = await db.execute(
        select(Deal).where(Deal.lead_id == lead_id, Deal.company_id == company_id)
    )
    related_deals = [
        RelatedDealBrief(
            id=d.id,
            title=d.title,
            status=d.status,
            value=float(d.value or 0),
            expected_close_date=d.expected_close_date,
        )
        for d in deals_result.scalars().all()
    ]

    client_brief = []
    if lead.email:
        client_match = await db.execute(
            select(Client).where(Client.company_id == company_id, Client.email == lead.email)
        )
        for c in client_match.scalars().all():
            client_brief.append(
                RelatedClientBrief(id=c.id, name=c.name, business_name=c.business_name, email=c.email)
            )

    return Record360View(
        entity_type="lead",
        entity_id=lead_id,
        entity=await _lead_out(db, lead),
        timeline=await _lead_timeline(db, lead_id, company_id),
        activities=activities,
        notes=notes,
        attachments=await _lead_attachments(db, lead_id, company_id),
        emails=await _lead_emails(db, lead_id, company_id),
        messaging=await _messaging_for_entity(db, company_id, user_id, lead_id=lead_id),
        tasks=[],
        meetings=_meetings_from_activities(activities),
        internal_comments=await _internal_comments(db, company_id, lead_id=lead_id),
        related=Record360Related(deals=related_deals, clients=client_brief),
        insights=_lead_insights(lead, activities),
    )


async def build_deal_360(
    db: AsyncSession, company_id: UUID, user_id: UUID, deal_id: UUID
) -> Record360View:
    result = await db.execute(select(Deal).where(Deal.id == deal_id, Deal.company_id == company_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    notes_result = await db.execute(
        select(DealNote).where(DealNote.deal_id == deal_id).order_by(DealNote.created_at.desc())
    )
    notes = []
    for n in notes_result.scalars().all():
        notes.append(
            DealNoteOut(
                id=n.id,
                deal_id=n.deal_id,
                content=n.content,
                created_by_id=n.created_by_id,
                created_by_name=await _creator_name(db, n.created_by_id),
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
        )

    activities = await _deal_activities(db, deal_id, company_id)
    act_rows = await db.execute(
        select(DealActivity).where(DealActivity.deal_id == deal_id).order_by(DealActivity.created_at.desc()).limit(20)
    )
    email_rows = await db.execute(
        select(DealEmail).where(DealEmail.deal_id == deal_id).order_by(DealEmail.sent_at.desc()).limit(10)
    )
    insights_data = compute_deal_insights(
        deal,
        recent_activities=list(act_rows.scalars().all()),
        recent_emails=list(email_rows.scalars().all()),
    )

    related_lead = []
    if deal.lead_id:
        lead = await db.get(Lead, deal.lead_id)
        if lead:
            related_lead = [
                RelatedLeadBrief(id=lead.id, name=lead.name, status=lead.status, company_name=lead.company_name)
            ]

    related_client = []
    if deal.client_id:
        client = await db.get(Client, deal.client_id)
        if client:
            related_client = [
                RelatedClientBrief(id=client.id, name=client.name, business_name=client.business_name, email=client.email)
            ]

    return Record360View(
        entity_type="deal",
        entity_id=deal_id,
        entity=await _deal_out(db, deal),
        timeline=await _deal_timeline(db, deal_id, company_id),
        activities=activities,
        notes=notes,
        attachments=await _deal_attachments(db, deal_id, company_id),
        emails=await _deal_emails(db, deal_id, company_id),
        messaging=await _messaging_for_entity(db, company_id, user_id, deal_id=deal_id, lead_id=deal.lead_id),
        tasks=[],
        meetings=_meetings_from_activities(activities),
        internal_comments=await _internal_comments(db, company_id, deal_id=deal_id),
        related=Record360Related(leads=related_lead, clients=related_client),
        insights=Record360Insights(
            score=insights_data.probability,
            confidence=insights_data.confidence,
            summary=insights_data.summary,
            recommendations=insights_data.recommendations,
        ),
    )


async def build_client_360(
    db: AsyncSession, company_id: UUID, user_id: UUID, client_id: UUID
) -> Record360View:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.company_id == company_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    projects_result = await db.execute(
        select(Project).where(Project.client_id == client_id, Project.company_id == company_id)
    )
    projects = []
    project_briefs = []
    for p in projects_result.scalars().all():
        task_count = await db.execute(select(func.count()).select_from(Task).where(Task.project_id == p.id))
        done_count = await db.execute(
            select(func.count()).select_from(Task).where(Task.project_id == p.id, Task.status == "done")
        )
        total = task_count.scalar_one() or 0
        done = done_count.scalar_one() or 0
        progress = int((done / total) * 100) if total else 0
        project_briefs.append(
            RelatedProjectBrief(id=p.id, title=p.title, status=p.status, end_date=p.end_date, progress_percent=progress)
        )
        projects.append(
            {
                "id": str(p.id),
                "title": p.title,
                "status": p.status,
                "end_date": p.end_date.isoformat() if p.end_date else None,
                "progress_percent": progress,
            }
        )

    invoices_result = await db.execute(
        select(Invoice).where(Invoice.client_id == client_id).order_by(Invoice.created_at.desc())
    )
    invoice_briefs = [
        RelatedInvoiceBrief(
            id=i.id,
            invoice_number=i.invoice_number,
            status=i.status,
            total=float(i.total),
            due_date=i.due_date,
        )
        for i in invoices_result.scalars().all()
    ]

    deals_result = await db.execute(
        select(Deal).where(Deal.client_id == client_id, Deal.company_id == company_id)
    )
    deal_briefs = [
        RelatedDealBrief(id=d.id, title=d.title, status=d.status, value=float(d.value or 0))
        for d in deals_result.scalars().all()
    ]

    unpaid = sum(1 for i in invoice_briefs if i.status in ("unpaid", "overdue"))
    recs = []
    if unpaid:
        recs.append(f"{unpaid} unpaid invoice(s) — follow up on payment.")
    if project_briefs:
        recs.append(f"{len(project_briefs)} active project(s) linked to this client.")

    return Record360View(
        entity_type="client",
        entity_id=client_id,
        entity={
            "id": str(client.id),
            "name": client.name,
            "business_name": client.business_name,
            "email": client.email,
            "phone": client.phone,
            "address": client.address,
            "gst_number": client.gst_number,
            "notes": client.notes,
            "created_at": client.created_at.isoformat(),
        },
        timeline=[],
        activities=None,
        notes=[],
        attachments=await _client_attachments(db, client_id, company_id),
        emails=[],
        messaging=await _messaging_for_entity(db, company_id, user_id, client_id=client_id),
        tasks=[],
        meetings=[],
        internal_comments=await _internal_comments(db, company_id, client_id=client_id),
        related=Record360Related(projects=project_briefs, invoices=invoice_briefs, deals=deal_briefs),
        insights=Record360Insights(
            summary=f"Client with {len(project_briefs)} project(s) and {len(invoice_briefs)} invoice(s).",
            recommendations=recs,
        ),
    )


async def build_project_360(
    db: AsyncSession, company_id: UUID, user_id: UUID, project_id: UUID
) -> Record360View:
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.id == project_id, Project.company_id == company_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tasks = [
        {
            "id": str(t.id),
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "assigned_to": str(t.assigned_to) if t.assigned_to else None,
        }
        for t in project.tasks
    ]
    total = len(project.tasks)
    done = sum(1 for t in project.tasks if t.status == "done")
    progress = int((done / total) * 100) if total else 0

    client_brief = []
    client = await db.get(Client, project.client_id)
    if client:
        client_brief = [
            RelatedClientBrief(id=client.id, name=client.name, business_name=client.business_name, email=client.email)
        ]

    overdue_tasks = sum(
        1 for t in project.tasks if t.due_date and t.due_date.date() < date.today() and t.status != "done"
    )
    recs = []
    if overdue_tasks:
        recs.append(f"{overdue_tasks} overdue task(s) on this project.")
    if project.end_date and project.end_date < date.today() and project.status not in ("completed",):
        recs.append("Project deadline has passed — update status or timeline.")

    return Record360View(
        entity_type="project",
        entity_id=project_id,
        entity={
            "id": str(project.id),
            "title": project.title,
            "description": project.description,
            "status": project.status,
            "budget": float(project.budget or 0),
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "end_date": project.end_date.isoformat() if project.end_date else None,
            "progress_percent": progress,
            "task_total": total,
            "task_done": done,
        },
        timeline=[],
        activities=None,
        notes=[],
        attachments=[],
        emails=[],
        messaging=[],
        tasks=tasks,
        meetings=[],
        internal_comments=await _internal_comments(db, company_id, project_id=project_id),
        related=Record360Related(clients=client_brief),
        insights=Record360Insights(
            score=progress,
            confidence="High" if progress >= 75 else "Medium" if progress >= 40 else "Low",
            summary=f"Project {progress}% complete with {total - done} task(s) remaining.",
            recommendations=recs,
        ),
    )


async def build_record_360(
    db: AsyncSession,
    company_id: UUID,
    user_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> Record360View:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid entity type. Use: {', '.join(sorted(ENTITY_TYPES))}")

    builders = {
        "lead": build_lead_360,
        "deal": build_deal_360,
        "client": build_client_360,
        "project": build_project_360,
    }
    return await builders[entity_type](db, company_id, user_id, entity_id)
