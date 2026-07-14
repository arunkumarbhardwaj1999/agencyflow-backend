from datetime import UTC, datetime
import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.automation_engine import fire_trigger
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.email import send_custom_email, split_subject_body
from app.core.html_sanitize import sanitize_note_html
from app.core.deal_timeline import log_deal_timeline, stage_label
from app.core.lead_duplicates import find_duplicate_leads
from app.core.lead_timeline import log_lead_timeline, status_label
from app.core.record_360 import build_record_360
from app.core.realtime import realtime_manager
from app.services.whatsapp_service import deliver_whatsapp
from app.db.session import get_db
from app.models.client import Client
from app.models.document import Document
from app.models.deal import Deal
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_email import LeadEmail
from app.models.lead_note import LeadNote
from app.models.lead_timeline import LeadTimeline
from app.models.user import User
from app.schemas.client import ClientOut
from app.schemas.common import MessageResponse
from app.schemas.document import DocumentOut, LeadAttachmentOut
from app.schemas.deal import STAGE_DEFAULT_PROBABILITY, CreateDealFromLeadRequest, DealOut
from app.schemas.lead import LeadCreate, LeadOut, LeadUpdate
from app.schemas.lead_activity import (
    ACTIVITY_LABELS,
    ACTIVITY_TYPES,
    LeadActivitiesGrouped,
    LeadActivityCreate,
    LeadActivityOut,
    LeadActivityUpdate,
)
from app.schemas.lead_email import (
    DuplicateLeadMatch,
    LeadAttachmentRename,
    LeadDuplicateCheckResponse,
    LeadEmailOut,
    LeadMergeRequest,
)
from app.schemas.lead_note import LeadNoteCreate, LeadNoteOut, LeadNoteUpdate
from app.schemas.record_360 import Record360View
from app.schemas.lead_timeline import (
    LeadSendEmailRequest,
    LeadTimelineOut,
    LeadWhatsAppRequest,
)

router = APIRouter(prefix="/leads", tags=["leads"])
settings = get_settings()

PREVIEWABLE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "application/pdf",
}

LEAD_STATUSES = {"new", "contacted", "proposal", "won", "lost"}


def _max_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > _max_bytes():
        raise HTTPException(
            status_code=413, detail=f"File too large (max {settings.max_upload_mb} MB)"
        )
    return data


def _timeline_out(entry: LeadTimeline, creator_name: str | None) -> LeadTimelineOut:
    return LeadTimelineOut(
        id=entry.id,
        lead_id=entry.lead_id,
        event_type=entry.event_type,
        description=entry.description,
        created_by_id=entry.created_by_id,
        created_by_name=creator_name,
        metadata=entry.meta,
        created_at=entry.created_at,
    )


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _note_out(db: AsyncSession, note: LeadNote) -> LeadNoteOut:
    return LeadNoteOut(
        id=note.id,
        lead_id=note.lead_id,
        content=note.content,
        created_by_id=note.created_by_id,
        created_by_name=await _creator_name(db, note.created_by_id),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _note_preview(content: str, limit: int = 120) -> str:
    plain = re.sub(r"<[^>]+>", "", content).strip()
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1] + "…"


async def _activity_out(db: AsyncSession, activity: LeadActivity) -> LeadActivityOut:
    label = ACTIVITY_LABELS.get(activity.activity_type, activity.activity_type.replace("_", " ").title())
    return LeadActivityOut(
        id=activity.id,
        lead_id=activity.lead_id,
        activity_type=activity.activity_type,
        activity_label=label,
        title=activity.title,
        notes=activity.notes,
        scheduled_at=activity.scheduled_at,
        completed_at=activity.completed_at,
        is_completed=activity.is_completed,
        assigned_to_id=activity.assigned_to_id,
        assigned_to_name=await _creator_name(db, activity.assigned_to_id),
        created_by_id=activity.created_by_id,
        created_by_name=await _creator_name(db, activity.created_by_id),
        created_at=activity.created_at,
        updated_at=activity.updated_at,
    )


def _default_activity_title(activity_type: str) -> str:
    return ACTIVITY_LABELS.get(activity_type, activity_type.replace("_", " ").title())


def _api_base() -> str:
    return f"{settings.backend_public_url.rstrip('/')}{settings.api_v1_prefix}"


def _attachment_urls(lead_id: UUID, doc_id: UUID, content_type: str) -> tuple[str, str | None]:
    base = _api_base()
    download = f"{base}/leads/{lead_id}/attachments/{doc_id}/download"
    preview = (
        f"{base}/leads/{lead_id}/attachments/{doc_id}/preview"
        if content_type in PREVIEWABLE_TYPES
        else None
    )
    return download, preview


async def _attachment_out(db: AsyncSession, doc: Document) -> LeadAttachmentOut:
    download, preview = _attachment_urls(doc.lead_id, doc.id, doc.content_type)
    return LeadAttachmentOut(
        id=doc.id,
        lead_id=doc.lead_id,
        filename=doc.filename,
        content_type=doc.content_type,
        size=doc.size,
        uploaded_by_id=doc.uploaded_by,
        uploaded_by_name=await _creator_name(db, doc.uploaded_by),
        uploaded_at=doc.created_at,
        preview_url=preview,
        download_url=download,
        is_previewable=doc.content_type in PREVIEWABLE_TYPES,
    )


async def _email_out(db: AsyncSession, email: LeadEmail) -> LeadEmailOut:
    return LeadEmailOut(
        id=email.id,
        lead_id=email.lead_id,
        subject=email.subject,
        body=email.body,
        from_email=email.from_email,
        to_email=email.to_email,
        delivery_status=email.delivery_status,
        open_status=email.open_status,
        opened_at=email.opened_at,
        sent_by_id=email.sent_by_id,
        sent_by_name=await _creator_name(db, email.sent_by_id),
        error_message=email.error_message,
        sent_at=email.sent_at,
    )


def _duplicate_matches(matches: list[tuple[Lead, list[str]]]) -> list[DuplicateLeadMatch]:
    return [
        DuplicateLeadMatch(
            lead_id=lead.id,
            name=lead.name,
            email=lead.email,
            phone=lead.phone,
            company_name=lead.company_name,
            status=lead.status,
            created_at=lead.created_at,
            match_fields=fields,
        )
        for lead, fields in matches
    ]


async def _raise_if_duplicates(
    db: AsyncSession,
    company_id: UUID,
    *,
    email: str | None,
    phone: str | None,
    company_name: str | None,
    exclude_lead_id: UUID | None,
    ignore_duplicates: bool,
) -> None:
    if ignore_duplicates:
        return
    matches = await find_duplicate_leads(
        db,
        company_id,
        email=email,
        phone=phone,
        company_name=company_name,
        exclude_lead_id=exclude_lead_id,
    )
    if matches:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Possible duplicate lead found",
                "duplicates": [m.model_dump(mode="json") for m in _duplicate_matches(matches)],
            },
        )


async def _get_lead_attachment(
    db: AsyncSession, lead_id: UUID, doc_id: UUID, company_id: UUID
) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.lead_id == lead_id,
            Document.company_id == company_id,
            Document.kind == "lead_attachment",
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return doc


async def _log_activity_timeline(
    db: AsyncSession,
    *,
    lead: Lead,
    activity: LeadActivity,
    current: CurrentUser,
    action: str,
) -> None:
    label = _default_activity_title(activity.activity_type)
    if action == "completed":
        desc = f"{label} completed"
        if activity.notes:
            desc = f"{desc}: {activity.notes}"
        event_type = "activity_completed"
    else:
        when = ""
        if activity.scheduled_at:
            when = f" for {activity.scheduled_at.strftime('%d %b %Y, %I:%M %p')}"
        desc = f"{label} scheduled{when}"
        if activity.notes:
            desc = f"{desc} — {activity.notes}"
        event_type = "activity_scheduled"
    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type=event_type,
        description=desc,
        created_by_id=current.id,
        metadata={"activity_id": str(activity.id), "activity_type": activity.activity_type},
    )


@router.get("", response_model=list[LeadOut])
async def list_leads(
    status: str | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(Lead).where(Lead.company_id == current.company_id).order_by(Lead.created_at.desc())
    if status:
        q = q.where(Lead.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/check-duplicates", response_model=LeadDuplicateCheckResponse)
async def check_lead_duplicates(
    email: str | None = None,
    phone: str | None = None,
    company_name: str | None = None,
    exclude_lead_id: UUID | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    matches = await find_duplicate_leads(
        db,
        current.company_id,
        email=email,
        phone=phone,
        company_name=company_name,
        exclude_lead_id=exclude_lead_id,
    )
    duplicates = _duplicate_matches(matches)
    return LeadDuplicateCheckResponse(
        has_duplicates=bool(duplicates),
        duplicates=duplicates,
    )


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use: {', '.join(LEAD_STATUSES)}")

    await _raise_if_duplicates(
        db,
        current.company_id,
        email=body.email,
        phone=body.phone,
        company_name=body.company_name,
        exclude_lead_id=None,
        ignore_duplicates=body.ignore_duplicates,
    )

    data = body.model_dump(exclude={"ignore_duplicates"})
    lead = Lead(company_id=current.company_id, **data)
    db.add(lead)
    await db.flush()
    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="lead_created",
        description=f"Lead created in {status_label(lead.status)} stage",
        created_by_id=current.id,
    )
    await db.refresh(lead)
    await fire_trigger(
        db,
        company_id=current.company_id,
        trigger_key="lead_created",
        entity_type="lead",
        entity_id=lead.id,
        context={"email": lead.email, "phone": lead.phone, "name": lead.name},
    )
    await realtime_manager.broadcast(current.company_id, "lead", f"New lead added: {lead.name}")
    return lead


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    return lead


@router.get("/{lead_id}/360", response_model=Record360View)
async def get_lead_360(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """360° view — timeline, activities, notes, attachments, emails, messaging, tasks, related records."""
    return await build_record_360(db, current.company_id, current.id, "lead", lead_id)


@router.get("/{lead_id}/timeline", response_model=list[LeadTimelineOut])
async def get_lead_timeline(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadTimeline)
        .where(LeadTimeline.lead_id == lead_id, LeadTimeline.company_id == current.company_id)
        .order_by(LeadTimeline.created_at.desc())
    )
    entries = list(result.scalars().all())
    out: list[LeadTimelineOut] = []
    for entry in entries:
        name = await _creator_name(db, entry.created_by_id)
        out.append(_timeline_out(entry, name))
    return out


@router.get("/{lead_id}/notes", response_model=list[LeadNoteOut])
async def list_lead_notes(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadNote)
        .where(LeadNote.lead_id == lead_id, LeadNote.company_id == current.company_id)
        .order_by(LeadNote.created_at.desc())
    )
    notes = list(result.scalars().all())
    return [await _note_out(db, n) for n in notes]


@router.post("/{lead_id}/notes", response_model=LeadNoteOut, status_code=status.HTTP_201_CREATED)
async def create_lead_note(
    lead_id: UUID,
    body: LeadNoteCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    content = sanitize_note_html(body.content.strip())
    if not content:
        raise HTTPException(status_code=400, detail="Note cannot be empty")

    note = LeadNote(
        company_id=current.company_id,
        lead_id=lead.id,
        content=content,
        created_by_id=current.id,
    )
    db.add(note)
    await db.flush()

    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="note_added",
        description=_note_preview(content),
        created_by_id=current.id,
        metadata={"note_id": str(note.id)},
    )
    await db.refresh(note)
    return await _note_out(db, note)


@router.patch("/{lead_id}/notes/{note_id}", response_model=LeadNoteOut)
async def update_lead_note(
    lead_id: UUID,
    note_id: UUID,
    body: LeadNoteUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadNote).where(
            LeadNote.id == note_id,
            LeadNote.lead_id == lead_id,
            LeadNote.company_id == current.company_id,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    content = sanitize_note_html(body.content.strip())
    if not content:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    note.content = content
    await db.flush()
    await db.refresh(note)
    return await _note_out(db, note)


@router.delete("/{lead_id}/notes/{note_id}", response_model=MessageResponse)
async def delete_lead_note(
    lead_id: UUID,
    note_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadNote).where(
            LeadNote.id == note_id,
            LeadNote.lead_id == lead_id,
            LeadNote.company_id == current.company_id,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    return MessageResponse(message="Note deleted")


@router.post("/{lead_id}/timeline/notes", response_model=LeadTimelineOut, status_code=status.HTTP_201_CREATED)
async def add_lead_note_legacy(
    lead_id: UUID,
    body: LeadNoteCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Backward-compatible alias — creates a lead note and returns timeline entry."""
    note = await create_lead_note(lead_id, body, current, db)
    result = await db.execute(
        select(LeadTimeline)
        .where(
            LeadTimeline.lead_id == lead_id,
            LeadTimeline.company_id == current.company_id,
            LeadTimeline.event_type == "note_added",
        )
        .order_by(LeadTimeline.created_at.desc())
        .limit(1)
    )
    entry = result.scalar_one()
    name = await _creator_name(db, current.id)
    return _timeline_out(entry, name)


@router.get("/{lead_id}/activities", response_model=LeadActivitiesGrouped)
async def list_lead_activities(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id, LeadActivity.company_id == current.company_id)
        .order_by(LeadActivity.created_at.desc())
    )
    activities = list(result.scalars().all())
    upcoming = [a for a in activities if not a.is_completed]
    completed = [a for a in activities if a.is_completed]

    upcoming.sort(
        key=lambda a: (
            a.scheduled_at is None,
            a.scheduled_at or a.created_at,
        )
    )
    completed.sort(key=lambda a: a.completed_at or a.created_at, reverse=True)

    out_upcoming = [await _activity_out(db, a) for a in upcoming]
    out_completed = [await _activity_out(db, a) for a in completed]
    return LeadActivitiesGrouped(upcoming=out_upcoming, completed=out_completed)


@router.post("/{lead_id}/activities", response_model=LeadActivityOut, status_code=status.HTTP_201_CREATED)
async def create_lead_activity(
    lead_id: UUID,
    body: LeadActivityCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    activity_type = body.activity_type.strip().lower()
    if activity_type not in ACTIVITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid activity type. Use: {', '.join(sorted(ACTIVITY_TYPES))}",
        )

    now = datetime.now(UTC)
    is_completed = body.mark_completed
    completed_at = now if is_completed else None
    scheduled_at = body.scheduled_at
    if scheduled_at and scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)

    activity = LeadActivity(
        company_id=current.company_id,
        lead_id=lead.id,
        activity_type=activity_type,
        title=body.title.strip() if body.title else _default_activity_title(activity_type),
        notes=body.notes.strip() if body.notes else None,
        scheduled_at=scheduled_at,
        completed_at=completed_at,
        is_completed=is_completed,
        assigned_to_id=body.assigned_to_id or current.id,
        created_by_id=current.id,
    )
    db.add(activity)
    await db.flush()

    if activity_type == "follow_up" and scheduled_at and not is_completed:
        lead.next_followup = scheduled_at
        await log_lead_timeline(
            db,
            lead_id=lead.id,
            company_id=current.company_id,
            event_type="followup_scheduled",
            description="Follow-up scheduled",
            created_by_id=current.id,
            metadata={"next_followup": scheduled_at.isoformat()},
        )

    await _log_activity_timeline(
        db,
        lead=lead,
        activity=activity,
        current=current,
        action="completed" if is_completed else "scheduled",
    )
    await db.refresh(activity)
    return await _activity_out(db, activity)


@router.patch("/{lead_id}/activities/{activity_id}", response_model=LeadActivityOut)
async def update_lead_activity(
    lead_id: UUID,
    activity_id: UUID,
    body: LeadActivityUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadActivity).where(
            LeadActivity.id == activity_id,
            LeadActivity.lead_id == lead_id,
            LeadActivity.company_id == current.company_id,
        )
    )
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    data = body.model_dump(exclude_unset=True)
    mark_completed = data.pop("mark_completed", None)

    for key, value in data.items():
        if key == "scheduled_at" and value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        setattr(activity, key, value)

    if mark_completed is True and not activity.is_completed:
        activity.is_completed = True
        activity.completed_at = datetime.now(UTC)
        await _log_activity_timeline(db, lead=lead, activity=activity, current=current, action="completed")
    elif mark_completed is False:
        activity.is_completed = False
        activity.completed_at = None

    if activity.activity_type == "follow_up" and activity.scheduled_at and not activity.is_completed:
        lead.next_followup = activity.scheduled_at

    await db.flush()
    await db.refresh(activity)
    return await _activity_out(db, activity)


@router.delete("/{lead_id}/activities/{activity_id}", response_model=MessageResponse)
async def delete_lead_activity(
    lead_id: UUID,
    activity_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadActivity).where(
            LeadActivity.id == activity_id,
            LeadActivity.lead_id == lead_id,
            LeadActivity.company_id == current.company_id,
        )
    )
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    await db.delete(activity)
    return MessageResponse(message="Activity deleted")


@router.post("/{lead_id}/send-email", response_model=MessageResponse)
async def send_lead_email(
    lead_id: UUID,
    body: LeadSendEmailRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email address")

    subject, text = split_subject_body(body.content, body.subject or "Following up on your enquiry")
    from_email = settings.email_from or settings.smtp_user or "noreply@agencyflow.in"
    sent, err = await send_custom_email(lead.email, subject, text)

    delivery_status = "delivered" if sent else "failed"
    email_row = LeadEmail(
        company_id=current.company_id,
        lead_id=lead.id,
        subject=subject,
        body=text,
        from_email=from_email,
        to_email=lead.email,
        delivery_status=delivery_status,
        open_status="unknown",
        sent_by_id=current.id,
        error_message=None if sent else (err or "Email could not be sent"),
    )
    db.add(email_row)
    await db.flush()

    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="email_sent",
        description=f"Email {'sent' if sent else 'failed'}: {subject}",
        created_by_id=current.id,
        metadata={"subject": subject, "email_id": str(email_row.id), "delivery_status": delivery_status},
    )

    if sent:
        if settings.email_enabled:
            return MessageResponse(message=f"Email sent to {lead.email}")
        return MessageResponse(message="Email logged (mock — configure SMTP to send for real)")
    return MessageResponse(message=err or "Email could not be sent — saved in email history as failed")


@router.get("/{lead_id}/emails", response_model=list[LeadEmailOut])
async def list_lead_emails(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(LeadEmail)
        .where(LeadEmail.lead_id == lead_id, LeadEmail.company_id == current.company_id)
        .order_by(LeadEmail.sent_at.desc())
    )
    emails = list(result.scalars().all())
    return [await _email_out(db, e) for e in emails]


@router.post("/{lead_id}/whatsapp", response_model=MessageResponse)
async def send_lead_whatsapp(
    lead_id: UUID,
    body: LeadWhatsAppRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    if not lead.phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")

    log = await deliver_whatsapp(
        company_id=current.company_id,
        client_id=None,
        phone=lead.phone,
        message=body.message.strip(),
        template_key=None,
        use_template=False,
    )
    if log.status == "failed":
        raise HTTPException(status_code=502, detail="WhatsApp could not be sent")

    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="whatsapp_sent",
        description=f"WhatsApp message sent to {lead.phone}",
        created_by_id=current.id,
    )
    return MessageResponse(message=f"WhatsApp sent to {lead.phone}")


@router.get("/{lead_id}/attachments", response_model=list[LeadAttachmentOut])
async def list_lead_attachments(
    lead_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_lead(db, lead_id, current.company_id)
    result = await db.execute(
        select(Document)
        .where(
            Document.lead_id == lead_id,
            Document.company_id == current.company_id,
            Document.kind == "lead_attachment",
        )
        .order_by(Document.created_at.desc())
    )
    docs = list(result.scalars().all())
    return [await _attachment_out(db, d) for d in docs]


@router.post("/{lead_id}/attachments", response_model=LeadAttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_lead_attachment(
    lead_id: UUID,
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    data = await _read_upload(file)
    content_type = file.content_type or storage.guess_content_type(file.filename or "")
    key = storage.build_key(current.company_id, "leads", file.filename or "file")
    await storage.save(key, data, content_type)

    doc = Document(
        company_id=current.company_id,
        lead_id=lead.id,
        uploaded_by=current.id,
        filename=file.filename or "file",
        content_type=content_type,
        size=len(data),
        storage_key=key,
        kind="lead_attachment",
    )
    db.add(doc)
    await db.flush()

    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="attachment_uploaded",
        description=f"Attachment uploaded: {doc.filename}",
        created_by_id=current.id,
        metadata={"document_id": str(doc.id), "filename": doc.filename},
    )

    return await _attachment_out(db, doc)


@router.get("/{lead_id}/attachments/{doc_id}/download")
async def download_lead_attachment(
    lead_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_lead_attachment(db, lead_id, doc_id, current.company_id)
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.get("/{lead_id}/attachments/{doc_id}/preview")
async def preview_lead_attachment(
    lead_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_lead_attachment(db, lead_id, doc_id, current.company_id)
    if doc.content_type not in PREVIEWABLE_TYPES:
        raise HTTPException(status_code=400, detail="This file type cannot be previewed")
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.patch("/{lead_id}/attachments/{doc_id}", response_model=LeadAttachmentOut)
async def rename_lead_attachment(
    lead_id: UUID,
    doc_id: UUID,
    body: LeadAttachmentRename,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_lead_attachment(db, lead_id, doc_id, current.company_id)
    doc.filename = body.filename.strip()
    await db.flush()
    await db.refresh(doc)
    return await _attachment_out(db, doc)


@router.delete("/{lead_id}/attachments/{doc_id}", response_model=MessageResponse)
async def delete_lead_attachment(
    lead_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_lead_attachment(db, lead_id, doc_id, current.company_id)
    await storage.delete(doc.storage_key)
    await db.delete(doc)
    return MessageResponse(message="Attachment deleted")


@router.post("/{lead_id}/create-deal", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal_from_lead(
    lead_id: UUID,
    body: CreateDealFromLeadRequest | None = None,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    from app.api.v1.deals import _deal_out, _next_kanban_position

    lead = await _get_lead(db, lead_id, current.company_id)
    opts = body or CreateDealFromLeadRequest()

    existing = await db.execute(
        select(Deal).where(
            Deal.lead_id == lead.id,
            Deal.company_id == current.company_id,
            Deal.status.not_in(("lost",)),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="An active deal already exists for this lead",
        )

    title = opts.title or f"{lead.company_name or lead.name} — Deal"
    deal = Deal(
        company_id=current.company_id,
        lead_id=lead.id,
        assigned_user_id=opts.assigned_user_id or lead.assigned_user_id or current.id,
        title=title.strip(),
        contact_name=lead.name,
        contact_email=lead.email,
        contact_phone=lead.phone,
        company_name=lead.company_name,
        value=opts.value if opts.value is not None else lead.value,
        probability=STAGE_DEFAULT_PROBABILITY["qualification"],
        expected_close_date=opts.expected_close_date,
        status="qualification",
        kanban_position=await _next_kanban_position(db, current.company_id, "qualification"),
        source=lead.source,
        notes=lead.notes,
    )
    db.add(deal)
    lead.status = "proposal"
    await db.flush()

    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="deal_created",
        description=f"Qualified — deal created: {deal.title}",
        created_by_id=current.id,
        metadata={"deal_id": str(deal.id)},
    )
    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="deal_created",
        description=f"Deal created from lead: {lead.name}",
        created_by_id=current.id,
        metadata={"lead_id": str(lead.id)},
    )
    await db.refresh(deal)
    await realtime_manager.broadcast(current.company_id, "deal", f"Deal created: {deal.title}")
    return await _deal_out(db, deal)


@router.post("/{lead_id}/convert", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def convert_lead(
    lead_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    from app.api.v1.clients import _enrich_client
    from app.core.plans import assert_can_add_client

    lead = await _get_lead(db, lead_id, current.company_id)
    await assert_can_add_client(db, current.company_id)
    if not lead.email:
        raise HTTPException(
            status_code=400,
            detail="Lead must have an email before converting to client",
        )
    existing = await db.execute(
        select(Client).where(Client.company_id == current.company_id, Client.email == lead.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A client with this email already exists")

    client = Client(
        company_id=current.company_id,
        assigned_user_id=lead.assigned_user_id,
        name=lead.name,
        business_name=lead.company_name or lead.name,
        email=lead.email,
        phone=lead.phone,
        notes=lead.notes,
    )
    db.add(client)
    lead.status = "won"
    await db.flush()
    await log_lead_timeline(
        db,
        lead_id=lead.id,
        company_id=current.company_id,
        event_type="converted_to_client",
        description=f"Lead converted to client: {client.business_name}",
        created_by_id=current.id,
        metadata={"client_id": str(client.id)},
    )
    await db.refresh(client)
    await realtime_manager.broadcast(
        current.company_id, "client", f"Lead converted to client: {client.business_name}"
    )
    return await _enrich_client(db, client)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    ignore_duplicates = data.pop("ignore_duplicates", False)

    if "status" in data and data["status"] not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    check_email = data.get("email", lead.email)
    check_phone = data.get("phone", lead.phone)
    check_company = data.get("company_name", lead.company_name)
    await _raise_if_duplicates(
        db,
        current.company_id,
        email=check_email,
        phone=check_phone,
        company_name=check_company,
        exclude_lead_id=lead.id,
        ignore_duplicates=ignore_duplicates,
    )

    old_status = lead.status
    old_assigned = lead.assigned_user_id
    old_followup = lead.next_followup

    for k, v in data.items():
        setattr(lead, k, v)

    if "status" in data and data["status"] != old_status:
        await log_lead_timeline(
            db,
            lead_id=lead.id,
            company_id=current.company_id,
            event_type="stage_changed",
            description=f"Stage changed from {status_label(old_status)} to {status_label(lead.status)}",
            created_by_id=current.id,
            metadata={"from": old_status, "to": lead.status},
        )
    if "assigned_user_id" in data and data["assigned_user_id"] != old_assigned:
        assignee = await _creator_name(db, lead.assigned_user_id)
        await log_lead_timeline(
            db,
            lead_id=lead.id,
            company_id=current.company_id,
            event_type="assigned",
            description=f"Assigned to {assignee or 'Unassigned'}",
            created_by_id=current.id,
        )
    if "next_followup" in data and data["next_followup"] != old_followup and lead.next_followup:
        await log_lead_timeline(
            db,
            lead_id=lead.id,
            company_id=current.company_id,
            event_type="followup_scheduled",
            description="Follow-up scheduled",
            created_by_id=current.id,
            metadata={"next_followup": lead.next_followup.isoformat()},
        )

    await db.flush()
    await db.refresh(lead)
    await realtime_manager.broadcast(current.company_id, "lead", f"Lead updated: {lead.name} ({lead.status})")
    return lead


@router.post("/{lead_id}/merge", response_model=LeadOut)
async def merge_leads(
    lead_id: UUID,
    body: LeadMergeRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_lead(db, lead_id, current.company_id)
    if body.source_lead_id == lead_id:
        raise HTTPException(status_code=400, detail="Cannot merge a lead into itself")

    source = await _get_lead(db, body.source_lead_id, current.company_id)

    for model, fk in [
        (LeadNote, "lead_id"),
        (LeadActivity, "lead_id"),
        (LeadTimeline, "lead_id"),
        (LeadEmail, "lead_id"),
        (Document, "lead_id"),
    ]:
        result = await db.execute(
            select(model).where(
                getattr(model, fk) == source.id,
                model.company_id == current.company_id,
            )
        )
        for row in result.scalars().all():
            setattr(row, fk, target.id)

    for field in ("email", "phone", "company_name", "notes", "assigned_user_id", "next_followup"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))

    if source.value and (not target.value or target.value == 0):
        target.value = source.value

    await log_lead_timeline(
        db,
        lead_id=target.id,
        company_id=current.company_id,
        event_type="lead_merged",
        description=f"Merged duplicate lead: {source.name}",
        created_by_id=current.id,
        metadata={"merged_lead_id": str(source.id)},
    )

    await db.delete(source)
    await db.flush()
    await db.refresh(target)
    return target


@router.delete("/{lead_id}", response_model=MessageResponse)
async def delete_lead(
    lead_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await _get_lead(db, lead_id, current.company_id)
    lead_name = lead.name
    await db.delete(lead)
    await realtime_manager.broadcast(current.company_id, "lead", f"Lead removed: {lead_name}")
    return MessageResponse(message="Lead deleted")


async def _get_lead(db: AsyncSession, lead_id: UUID, company_id: UUID) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
