from datetime import date, datetime
from app.core.utc import UTC
import re
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.automation_engine import fire_trigger
from app.core.config import get_settings
from app.core.deal_insights import compute_deal_insights
from app.core.deal_timeline import log_deal_timeline, stage_label
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.email import send_custom_email, split_subject_body
from app.core.html_sanitize import sanitize_note_html
from app.core.lead_timeline import log_lead_timeline
from app.core.plans import assert_can_add_client
from app.core.realtime import realtime_manager
from app.core.record_360 import build_record_360
from app.db.session import get_db
from app.models.client import Client
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_email import DealEmail
from app.models.deal_note import DealNote
from app.models.deal_timeline import DealTimeline
from app.models.document import Document
from app.models.lead import Lead
from app.models.user import User
from app.schemas.client import ClientOut
from app.schemas.common import MessageResponse
from app.schemas.deal import (
    DEAL_STAGES,
    STAGE_DEFAULT_PROBABILITY,
    CreateDealFromLeadRequest,
    DealCreate,
    DealInsights,
    DealKanbanBoard,
    DealKanbanColumn,
    DealKanbanMove,
    DealOut,
    DealUpdate,
)
from app.schemas.record_360 import Record360View
from app.schemas.deal_activity import (
    DEAL_ACTIVITY_LABELS,
    DEAL_ACTIVITY_TYPES,
    DealActivitiesGrouped,
    DealActivityCreate,
    DealActivityOut,
    DealActivityUpdate,
    DealAttachmentRename,
    DealEmailOut,
    DealNoteCreate,
    DealNoteOut,
    DealNoteUpdate,
)
from app.schemas.deal_timeline import DealSendEmailRequest, DealTimelineOut
from app.schemas.document import DealAttachmentOut

router = APIRouter(prefix="/deals", tags=["deals"])
settings = get_settings()

PREVIEWABLE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "application/pdf",
}


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


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _get_deal(db: AsyncSession, deal_id: UUID, company_id: UUID) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id, Deal.company_id == company_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


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


def _api_base() -> str:
    return f"{settings.backend_public_url.rstrip('/')}{settings.api_v1_prefix}"


def _attachment_urls(deal_id: UUID, doc_id: UUID, content_type: str) -> tuple[str, str | None]:
    base = _api_base()
    download = f"{base}/deals/{deal_id}/attachments/{doc_id}/download"
    preview = (
        f"{base}/deals/{deal_id}/attachments/{doc_id}/preview"
        if content_type in PREVIEWABLE_TYPES
        else None
    )
    return download, preview


async def _attachment_out(db: AsyncSession, doc: Document) -> DealAttachmentOut:
    download, preview = _attachment_urls(doc.deal_id, doc.id, doc.content_type)
    return DealAttachmentOut(
        id=doc.id,
        deal_id=doc.deal_id,
        filename=doc.filename,
        content_type=doc.content_type,
        size=doc.size,
        kind=doc.kind,
        is_proposal=doc.kind == "deal_proposal",
        uploaded_by_id=doc.uploaded_by,
        uploaded_by_name=await _creator_name(db, doc.uploaded_by),
        uploaded_at=doc.created_at,
        preview_url=preview,
        download_url=download,
        is_previewable=doc.content_type in PREVIEWABLE_TYPES,
    )


def _timeline_out(entry: DealTimeline, creator_name: str | None) -> DealTimelineOut:
    return DealTimelineOut(
        id=entry.id,
        deal_id=entry.deal_id,
        event_type=entry.event_type,
        description=entry.description,
        created_by_id=entry.created_by_id,
        created_by_name=creator_name,
        metadata=entry.meta,
        created_at=entry.created_at,
    )


def _note_preview(content: str, limit: int = 120) -> str:
    plain = re.sub(r"<[^>]+>", "", content).strip()
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1] + "…"


async def _note_out(db: AsyncSession, note: DealNote) -> DealNoteOut:
    return DealNoteOut(
        id=note.id,
        deal_id=note.deal_id,
        content=note.content,
        created_by_id=note.created_by_id,
        created_by_name=await _creator_name(db, note.created_by_id),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def _activity_out(db: AsyncSession, activity: DealActivity) -> DealActivityOut:
    label = DEAL_ACTIVITY_LABELS.get(
        activity.activity_type, activity.activity_type.replace("_", " ").title()
    )
    return DealActivityOut(
        id=activity.id,
        deal_id=activity.deal_id,
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


async def _email_out(db: AsyncSession, email: DealEmail) -> DealEmailOut:
    return DealEmailOut(
        id=email.id,
        deal_id=email.deal_id,
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


async def _get_deal_attachment(
    db: AsyncSession, deal_id: UUID, doc_id: UUID, company_id: UUID
) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.deal_id == deal_id,
            Document.company_id == company_id,
            Document.kind.in_(("deal_attachment", "deal_proposal")),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return doc


async def _next_kanban_position(db: AsyncSession, company_id: UUID, status: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Deal.kanban_position), -1)).where(
            Deal.company_id == company_id, Deal.status == status
        )
    )
    return int(result.scalar_one()) + 1


async def _win_deal(
    db: AsyncSession,
    deal: Deal,
    current: CurrentUser,
) -> Client:
    if deal.status == "won" and deal.client_id:
        client = await db.get(Client, deal.client_id)
        if client:
            return client

    if not deal.contact_email:
        raise HTTPException(status_code=400, detail="Deal must have a contact email to win")

    await assert_can_add_client(db, current.company_id)
    existing = await db.execute(
        select(Client).where(
            Client.company_id == current.company_id,
            Client.email == deal.contact_email,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A client with this email already exists")

    client = Client(
        company_id=current.company_id,
        assigned_user_id=deal.assigned_user_id,
        name=deal.contact_name or deal.title,
        business_name=deal.company_name or deal.contact_name or deal.title,
        email=deal.contact_email,
        phone=deal.contact_phone,
        notes=deal.notes,
    )
    db.add(client)
    await db.flush()

    deal.status = "won"
    deal.probability = 100
    deal.client_id = client.id

    if deal.lead_id:
        lead = await db.get(Lead, deal.lead_id)
        if lead and lead.company_id == current.company_id:
            lead.status = "won"
            await log_lead_timeline(
                db,
                lead_id=lead.id,
                company_id=current.company_id,
                event_type="converted_to_client",
                description=f"Lead won via deal: {deal.title}",
                created_by_id=current.id,
                metadata={"deal_id": str(deal.id), "client_id": str(client.id)},
            )

    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="deal_won",
        description=f"Deal won — client created: {client.business_name}",
        created_by_id=current.id,
        metadata={"client_id": str(client.id)},
    )
    await fire_trigger(
        db,
        company_id=current.company_id,
        trigger_key="deal_won",
        entity_type="deal",
        entity_id=deal.id,
        context={
            "name": client.name,
            "email": client.email,
            "phone": client.phone,
            "client_id": str(client.id),
        },
    )
    return client


@router.get("", response_model=list[DealOut])
async def list_deals(
    status: str | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(Deal).where(Deal.company_id == current.company_id).order_by(
        Deal.kanban_position.asc(), Deal.created_at.desc()
    )
    if status:
        q = q.where(Deal.status == status)
    result = await db.execute(q)
    deals = list(result.scalars().all())
    return [await _deal_out(db, d) for d in deals]


@router.get("/kanban", response_model=DealKanbanBoard)
async def get_deals_kanban(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Deal)
        .where(Deal.company_id == current.company_id)
        .order_by(Deal.kanban_position.asc(), Deal.updated_at.desc())
    )
    deals = list(result.scalars().all())
    grouped: dict[str, list[DealOut]] = {stage: [] for stage in DEAL_STAGES}
    total_value = Decimal("0")
    open_count = 0

    for deal in deals:
        out = await _deal_out(db, deal)
        if deal.status in grouped:
            grouped[deal.status].append(out)
        if deal.status not in {"won", "lost"}:
            total_value += Decimal(str(deal.value or 0))
            open_count += 1

    columns = [
        DealKanbanColumn(stage=stage, label=stage_label(stage), deals=grouped[stage])
        for stage in DEAL_STAGES
    ]
    return DealKanbanBoard(
        columns=columns,
        total_pipeline_value=total_value,
        open_deal_count=open_count,
    )


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal(
    body: DealCreate,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in DEAL_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Use: {', '.join(DEAL_STAGES)}")

    probability = body.probability
    if probability is None:
        probability = STAGE_DEFAULT_PROBABILITY.get(body.status, 50)

    position = await _next_kanban_position(db, current.company_id, body.status)
    deal = Deal(
        company_id=current.company_id,
        lead_id=body.lead_id,
        assigned_user_id=body.assigned_user_id or current.id,
        title=body.title.strip(),
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
        company_name=body.company_name,
        value=body.value,
        probability=probability,
        expected_close_date=body.expected_close_date,
        status=body.status,
        kanban_position=position,
        source=body.source,
        notes=body.notes,
    )
    db.add(deal)
    await db.flush()

    if body.lead_id:
        lead = await db.get(Lead, body.lead_id)
        if lead and lead.company_id == current.company_id:
            lead.status = "proposal"
            await log_lead_timeline(
                db,
                lead_id=lead.id,
                company_id=current.company_id,
                event_type="deal_created",
                description=f"Deal created: {deal.title}",
                created_by_id=current.id,
                metadata={"deal_id": str(deal.id)},
            )

    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="deal_created",
        description=f"Deal created in {stage_label(deal.status)}",
        created_by_id=current.id,
    )
    await db.refresh(deal)
    await realtime_manager.broadcast(current.company_id, "deal", f"New deal: {deal.title}")
    return await _deal_out(db, deal)


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    return await _deal_out(db, deal)


@router.get("/{deal_id}/360", response_model=Record360View)
async def get_deal_360(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    return await build_record_360(db, current.company_id, current.id, "deal", deal_id)


@router.get("/{deal_id}/insights", response_model=DealInsights)
async def get_deal_insights(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    act_result = await db.execute(
        select(DealActivity)
        .where(DealActivity.deal_id == deal_id)
        .order_by(DealActivity.created_at.desc())
        .limit(20)
    )
    email_result = await db.execute(
        select(DealEmail)
        .where(DealEmail.deal_id == deal_id)
        .order_by(DealEmail.sent_at.desc())
        .limit(10)
    )
    return compute_deal_insights(
        deal,
        recent_activities=list(act_result.scalars().all()),
        recent_emails=list(email_result.scalars().all()),
    )


@router.patch("/{deal_id}", response_model=DealOut)
async def update_deal(
    deal_id: UUID,
    body: DealUpdate,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    old_status = deal.status

    if "status" in data and data["status"] not in DEAL_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    for key, value in data.items():
        setattr(deal, key, value)

    if "status" in data and data["status"] != old_status:
        if data["status"] == "won":
            await _win_deal(db, deal, current)
        elif data["status"] == "lost":
            deal.probability = 0
            await log_deal_timeline(
                db,
                deal_id=deal.id,
                company_id=current.company_id,
                event_type="deal_lost",
                description=f"Deal marked as lost{f': {deal.lost_reason}' if deal.lost_reason else ''}",
                created_by_id=current.id,
            )
        else:
            if deal.probability == STAGE_DEFAULT_PROBABILITY.get(old_status):
                deal.probability = STAGE_DEFAULT_PROBABILITY.get(deal.status, deal.probability)
            await log_deal_timeline(
                db,
                deal_id=deal.id,
                company_id=current.company_id,
                event_type="stage_changed",
                description=f"Stage changed from {stage_label(old_status)} to {stage_label(deal.status)}",
                created_by_id=current.id,
                metadata={"from": old_status, "to": deal.status},
            )

    await db.flush()
    await db.refresh(deal)
    return await _deal_out(db, deal)


@router.patch("/{deal_id}/kanban", response_model=DealOut)
async def move_deal_kanban(
    deal_id: UUID,
    body: DealKanbanMove,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    if body.status not in DEAL_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

    old_status = deal.status
    deal.status = body.status
    deal.kanban_position = body.kanban_position

    if body.status == "won" and old_status != "won":
        await _win_deal(db, deal, current)
    elif body.status == "lost" and old_status != "lost":
        deal.probability = 0
        await log_deal_timeline(
            db,
            deal_id=deal.id,
            company_id=current.company_id,
            event_type="deal_lost",
            description="Deal marked as lost",
            created_by_id=current.id,
        )
    elif body.status != old_status:
        await log_deal_timeline(
            db,
            deal_id=deal.id,
            company_id=current.company_id,
            event_type="stage_changed",
            description=f"Moved to {stage_label(body.status)}",
            created_by_id=current.id,
            metadata={"from": old_status, "to": body.status},
        )

    await db.flush()
    await db.refresh(deal)
    return await _deal_out(db, deal)


@router.post("/{deal_id}/win", response_model=ClientOut)
async def win_deal(
    deal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    from app.api.v1.clients import _enrich_client

    deal = await _get_deal(db, deal_id, current.company_id)
    client = await _win_deal(db, deal, current)
    await db.refresh(client)
    await realtime_manager.broadcast(
        current.company_id, "client", f"Deal won — client created: {client.business_name}"
    )
    return await _enrich_client(db, client)


@router.delete("/{deal_id}", response_model=MessageResponse)
async def delete_deal(
    deal_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    if deal.status == "won":
        raise HTTPException(status_code=400, detail="Cannot delete a won deal with linked client")
    await db.delete(deal)
    return MessageResponse(message="Deal deleted")


@router.get("/{deal_id}/timeline", response_model=list[DealTimelineOut])
async def get_deal_timeline(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealTimeline)
        .where(DealTimeline.deal_id == deal_id, DealTimeline.company_id == current.company_id)
        .order_by(DealTimeline.created_at.desc())
    )
    entries = list(result.scalars().all())
    out: list[DealTimelineOut] = []
    for entry in entries:
        name = await _creator_name(db, entry.created_by_id)
        out.append(_timeline_out(entry, name))
    return out


@router.get("/{deal_id}/notes", response_model=list[DealNoteOut])
async def list_deal_notes(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealNote)
        .where(DealNote.deal_id == deal_id, DealNote.company_id == current.company_id)
        .order_by(DealNote.created_at.desc())
    )
    return [await _note_out(db, n) for n in result.scalars().all()]


@router.post("/{deal_id}/notes", response_model=DealNoteOut, status_code=status.HTTP_201_CREATED)
async def create_deal_note(
    deal_id: UUID,
    body: DealNoteCreate,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    content = sanitize_note_html(body.content.strip())
    if not content:
        raise HTTPException(status_code=400, detail="Note cannot be empty")

    note = DealNote(
        company_id=current.company_id,
        deal_id=deal.id,
        content=content,
        created_by_id=current.id,
    )
    db.add(note)
    await db.flush()
    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="note_added",
        description=_note_preview(content),
        created_by_id=current.id,
        metadata={"note_id": str(note.id)},
    )
    await db.refresh(note)
    return await _note_out(db, note)


@router.patch("/{deal_id}/notes/{note_id}", response_model=DealNoteOut)
async def update_deal_note(
    deal_id: UUID,
    note_id: UUID,
    body: DealNoteUpdate,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealNote).where(
            DealNote.id == note_id,
            DealNote.deal_id == deal_id,
            DealNote.company_id == current.company_id,
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


@router.delete("/{deal_id}/notes/{note_id}", response_model=MessageResponse)
async def delete_deal_note(
    deal_id: UUID,
    note_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealNote).where(
            DealNote.id == note_id,
            DealNote.deal_id == deal_id,
            DealNote.company_id == current.company_id,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    return MessageResponse(message="Note deleted")


@router.get("/{deal_id}/activities", response_model=DealActivitiesGrouped)
async def list_deal_activities(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealActivity)
        .where(DealActivity.deal_id == deal_id, DealActivity.company_id == current.company_id)
        .order_by(DealActivity.created_at.desc())
    )
    activities = list(result.scalars().all())
    upcoming = [a for a in activities if not a.is_completed]
    completed = [a for a in activities if a.is_completed]
    upcoming.sort(key=lambda a: (a.scheduled_at is None, a.scheduled_at or a.created_at))
    completed.sort(key=lambda a: a.completed_at or a.created_at, reverse=True)
    return DealActivitiesGrouped(
        upcoming=[await _activity_out(db, a) for a in upcoming],
        completed=[await _activity_out(db, a) for a in completed],
    )


@router.post("/{deal_id}/activities", response_model=DealActivityOut, status_code=status.HTTP_201_CREATED)
async def create_deal_activity(
    deal_id: UUID,
    body: DealActivityCreate,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    activity_type = body.activity_type.strip().lower()
    if activity_type not in DEAL_ACTIVITY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid activity type")

    now = datetime.now(UTC)
    scheduled_at = body.scheduled_at
    if scheduled_at and scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)

    activity = DealActivity(
        company_id=current.company_id,
        deal_id=deal.id,
        activity_type=activity_type,
        title=body.title.strip() if body.title else DEAL_ACTIVITY_LABELS.get(activity_type, activity_type),
        notes=body.notes.strip() if body.notes else None,
        scheduled_at=scheduled_at,
        completed_at=now if body.mark_completed else None,
        is_completed=body.mark_completed,
        assigned_to_id=body.assigned_to_id or current.id,
        created_by_id=current.id,
    )
    db.add(activity)
    await db.flush()
    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="activity_completed" if body.mark_completed else "activity_scheduled",
        description=activity.title or activity_type,
        created_by_id=current.id,
        metadata={"activity_id": str(activity.id)},
    )
    await db.refresh(activity)
    return await _activity_out(db, activity)


@router.post("/{deal_id}/send-email", response_model=MessageResponse)
async def send_deal_email(
    deal_id: UUID,
    body: DealSendEmailRequest,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    if not deal.contact_email:
        raise HTTPException(status_code=400, detail="Deal has no contact email")

    subject, text = split_subject_body(body.content, body.subject or f"Re: {deal.title}")
    from_email = settings.email_from or settings.smtp_user or "noreply@agencyflow.in"
    sent, err = await send_custom_email(deal.contact_email, subject, text)

    email_row = DealEmail(
        company_id=current.company_id,
        deal_id=deal.id,
        subject=subject,
        body=text,
        from_email=from_email,
        to_email=deal.contact_email,
        delivery_status="delivered" if sent else "failed",
        open_status="unknown",
        sent_by_id=current.id,
        error_message=None if sent else (err or "Email could not be sent"),
    )
    db.add(email_row)
    await db.flush()
    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="email_sent",
        description=f"Email {'sent' if sent else 'failed'}: {subject}",
        created_by_id=current.id,
        metadata={"email_id": str(email_row.id)},
    )
    if sent:
        return MessageResponse(message=f"Email sent to {deal.contact_email}")
    return MessageResponse(message=err or "Email failed — saved in history")


@router.get("/{deal_id}/emails", response_model=list[DealEmailOut])
async def list_deal_emails(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(DealEmail)
        .where(DealEmail.deal_id == deal_id, DealEmail.company_id == current.company_id)
        .order_by(DealEmail.sent_at.desc())
    )
    return [await _email_out(db, e) for e in result.scalars().all()]


@router.get("/{deal_id}/attachments", response_model=list[DealAttachmentOut])
async def list_deal_attachments(
    deal_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_deal(db, deal_id, current.company_id)
    result = await db.execute(
        select(Document)
        .where(
            Document.deal_id == deal_id,
            Document.company_id == current.company_id,
            Document.kind.in_(("deal_attachment", "deal_proposal")),
        )
        .order_by(Document.created_at.desc())
    )
    return [await _attachment_out(db, d) for d in result.scalars().all()]


@router.post("/{deal_id}/attachments", response_model=DealAttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_deal_attachment(
    deal_id: UUID,
    file: UploadFile = File(...),
    is_proposal: bool = Query(False),
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal(db, deal_id, current.company_id)
    data = await _read_upload(file)
    content_type = file.content_type or storage.guess_content_type(file.filename or "")
    key = storage.build_key(current.company_id, "deals", file.filename or "file")
    await storage.save(key, data, content_type)

    kind = "deal_proposal" if is_proposal else "deal_attachment"
    doc = Document(
        company_id=current.company_id,
        deal_id=deal.id,
        uploaded_by=current.id,
        filename=file.filename or "file",
        content_type=content_type,
        size=len(data),
        storage_key=key,
        kind=kind,
    )
    db.add(doc)
    await db.flush()

    if is_proposal and deal.status == "qualification":
        deal.status = "proposal_sent"
        deal.probability = max(deal.probability, STAGE_DEFAULT_PROBABILITY["proposal_sent"])

    await log_deal_timeline(
        db,
        deal_id=deal.id,
        company_id=current.company_id,
        event_type="proposal_uploaded" if is_proposal else "attachment_uploaded",
        description=f"{'Proposal' if is_proposal else 'Attachment'} uploaded: {doc.filename}",
        created_by_id=current.id,
        metadata={"document_id": str(doc.id), "filename": doc.filename},
    )
    return await _attachment_out(db, doc)


@router.get("/{deal_id}/attachments/{doc_id}/download")
async def download_deal_attachment(
    deal_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_deal_attachment(db, deal_id, doc_id, current.company_id)
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.get("/{deal_id}/attachments/{doc_id}/preview")
async def preview_deal_attachment(
    deal_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_deal_attachment(db, deal_id, doc_id, current.company_id)
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


@router.patch("/{deal_id}/attachments/{doc_id}", response_model=DealAttachmentOut)
async def rename_deal_attachment(
    deal_id: UUID,
    doc_id: UUID,
    body: DealAttachmentRename,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_deal_attachment(db, deal_id, doc_id, current.company_id)
    doc.filename = body.filename.strip()
    await db.flush()
    await db.refresh(doc)
    return await _attachment_out(db, doc)


@router.delete("/{deal_id}/attachments/{doc_id}", response_model=MessageResponse)
async def delete_deal_attachment(
    deal_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_deals")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_deal_attachment(db, deal_id, doc_id, current.company_id)
    await storage.delete(doc.storage_key)
    await db.delete(doc)
    return MessageResponse(message="Attachment deleted")
