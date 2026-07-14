from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.communication_service import (
    build_inbox_summary,
    date_filter_range,
    fetch_inbox_items,
)
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.sms import SMSError, send_sms
from app.db.session import get_db
from app.models.client import Client
from app.models.communication import InboxReadMark, InternalComment, SmsLog
from app.models.deal import Deal
from app.models.lead import Lead
from app.schemas.common import MessageResponse
from app.schemas.communication import (
    InboxResponse,
    InboxSummary,
    InternalCommentCreate,
    InternalCommentOut,
    MarkReadRequest,
    SendMessagingRequest,
)

router = APIRouter(prefix="/communications", tags=["communications"])
settings = get_settings()

INBOX_CHANNELS = {"all", "email", "messaging", "whatsapp", "call", "notification", "internal_comment"}


async def _author_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    from app.models.user import User

    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


@router.get("/inbox", response_model=InboxResponse)
async def get_inbox(
    channel: str = Query("all"),
    unread: bool = False,
    date_filter: str | None = Query(None, alias="date"),
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if channel not in INBOX_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Invalid channel. Use: {', '.join(sorted(INBOX_CHANNELS))}")

    range_start, range_end = date_filter_range(date_filter)
    items = await fetch_inbox_items(
        db,
        current.company_id,
        current.id,
        channel=channel,
        unread_only=unread,
        search=search,
        range_start=range_start,
        range_end=range_end,
        limit=limit,
    )
    unread_count = sum(1 for i in items if i.read_status == "unread")
    return InboxResponse(items=items, total=len(items), unread_count=unread_count)


@router.get("/summary", response_model=InboxSummary)
async def get_inbox_summary(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    return await build_inbox_summary(db, current.company_id, current.id)


@router.post("/mark-read", response_model=MessageResponse)
async def mark_items_read(
    body: MarkReadRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    for key in body.item_keys:
        existing = await db.execute(
            select(InboxReadMark).where(
                InboxReadMark.user_id == current.id,
                InboxReadMark.item_key == key,
            )
        )
        if existing.scalar_one_or_none():
            continue
        db.add(
            InboxReadMark(
                company_id=current.company_id,
                user_id=current.id,
                item_key=key,
            )
        )
    return MessageResponse(message="Marked as read")


@router.post("/internal-comments", response_model=InternalCommentOut, status_code=status.HTTP_201_CREATED)
async def create_internal_comment(
    body: InternalCommentCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    if not any([body.lead_id, body.deal_id, body.client_id, body.project_id, body.invoice_id]):
        raise HTTPException(status_code=400, detail="Link comment to a lead, deal, client, project, or invoice")

    comment = InternalComment(
        company_id=current.company_id,
        author_id=current.id,
        lead_id=body.lead_id,
        deal_id=body.deal_id,
        client_id=body.client_id,
        project_id=body.project_id,
        invoice_id=body.invoice_id,
        body=body.body.strip(),
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return InternalCommentOut(
        id=comment.id,
        body=comment.body,
        author_id=comment.author_id,
        author_name=await _author_name(db, comment.author_id),
        lead_id=comment.lead_id,
        deal_id=comment.deal_id,
        client_id=comment.client_id,
        project_id=comment.project_id,
        invoice_id=comment.invoice_id,
        created_at=comment.created_at,
    )


@router.get("/internal-comments", response_model=list[InternalCommentOut])
async def list_internal_comments(
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    client_id: UUID | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(InternalComment).where(InternalComment.company_id == current.company_id)
    if lead_id:
        q = q.where(InternalComment.lead_id == lead_id)
    if deal_id:
        q = q.where(InternalComment.deal_id == deal_id)
    if client_id:
        q = q.where(InternalComment.client_id == client_id)
    q = q.order_by(InternalComment.created_at.desc())
    result = await db.execute(q)
    comments = list(result.scalars().all())
    out: list[InternalCommentOut] = []
    for c in comments:
        out.append(
            InternalCommentOut(
                id=c.id,
                body=c.body,
                author_id=c.author_id,
                author_name=await _author_name(db, c.author_id),
                lead_id=c.lead_id,
                deal_id=c.deal_id,
                client_id=c.client_id,
                project_id=c.project_id,
                invoice_id=c.invoice_id,
                created_at=c.created_at,
            )
        )
    return out


@router.post("/send-message", response_model=MessageResponse)
async def send_messaging_proxy(
    body: SendMessagingRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Send SMS as WhatsApp proxy (no Meta API key required)."""
    phone = body.phone
    lead_id = body.lead_id
    deal_id = body.deal_id
    client_id = body.client_id

    if lead_id:
        lead = await db.get(Lead, lead_id)
        if not lead or lead.company_id != current.company_id:
            raise HTTPException(status_code=404, detail="Lead not found")
        phone = phone or lead.phone
    elif deal_id:
        deal = await db.get(Deal, deal_id)
        if not deal or deal.company_id != current.company_id:
            raise HTTPException(status_code=404, detail="Deal not found")
        phone = phone or deal.contact_phone
        lead_id = deal.lead_id
    elif client_id:
        client = await db.get(Client, client_id)
        if not client or client.company_id != current.company_id:
            raise HTTPException(status_code=404, detail="Client not found")
        phone = phone or client.phone

    if not phone:
        raise HTTPException(status_code=400, detail="No phone number available")

    message = body.message.strip()
    delivery_status = "delivered"
    error_message: str | None = None

    try:
        result = await send_sms(phone, message)
        if result.get("status") == "mock":
            delivery_status = "sent"
    except SMSError as exc:
        delivery_status = "failed"
        error_message = str(exc)

    sms = SmsLog(
        company_id=current.company_id,
        lead_id=lead_id,
        deal_id=deal_id,
        client_id=client_id,
        phone=phone,
        message=message,
        status=delivery_status,
        read_status="unknown",
        sent_by_id=current.id,
        error_message=error_message,
        is_proxy_for_whatsapp=True,
    )
    db.add(sms)
    await db.flush()

    if delivery_status == "failed":
        return MessageResponse(message=error_message or "Message failed — logged in inbox")

    label = "SMS sent (WhatsApp proxy)"
    if settings.sms_enabled:
        label = "Message sent via SMS"
    return MessageResponse(message=label)
