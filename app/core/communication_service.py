"""Unified communication inbox — aggregates emails, SMS (WhatsApp proxy), calls, notifications, comments."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.communication import InboxReadMark, InternalComment, SmsLog
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_email import DealEmail
from app.models.deal_timeline import DealTimeline
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_email import LeadEmail
from app.models.lead_timeline import LeadTimeline
from app.models.task import Task
from app.models.user import User
from app.models.whatsapp_log import WhatsAppLog
from app.schemas.communication import InboxItemOut, InboxSummary

settings = get_settings()

NOTIFICATION_EVENTS = {
    "lead_created",
    "converted_to_client",
    "deal_created",
    "deal_won",
    "deal_lost",
    "stage_changed",
    "attachment_uploaded",
    "proposal_uploaded",
}


def _preview(text: str, limit: int = 140) -> str:
    clean = (text or "").strip().replace("\n", " ")
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


async def _user_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _read_keys(db: AsyncSession, user_id: UUID) -> set[str]:
    result = await db.execute(select(InboxReadMark.item_key).where(InboxReadMark.user_id == user_id))
    return set(result.scalars().all())


def _item(
    *,
    key: str,
    channel: str,
    channel_label: str,
    title: str,
    preview: str,
    created_at: datetime,
    link_path: str,
    read_keys: set[str],
    contact_name: str | None = None,
    status: str | None = None,
    delivery_status: str | None = None,
    is_proxy: bool = False,
    sender_name: str | None = None,
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    client_id: UUID | None = None,
    project_id: UUID | None = None,
    invoice_id: UUID | None = None,
    metadata: dict | None = None,
) -> InboxItemOut:
    return InboxItemOut(
        id=key,
        channel=channel,
        channel_label=channel_label,
        title=title,
        preview=preview,
        contact_name=contact_name,
        status=status,
        delivery_status=delivery_status,
        read_status="read" if key in read_keys else "unread",
        created_at=created_at,
        is_proxy=is_proxy,
        sender_name=sender_name,
        lead_id=lead_id,
        deal_id=deal_id,
        client_id=client_id,
        project_id=project_id,
        invoice_id=invoice_id,
        link_path=link_path,
        metadata=metadata,
    )


async def fetch_inbox_items(
    db: AsyncSession,
    company_id: UUID,
    user_id: UUID,
    *,
    channel: str | None = None,
    unread_only: bool = False,
    search: str | None = None,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
    limit: int = 100,
) -> list[InboxItemOut]:
    read_keys = await _read_keys(db, user_id)
    items: list[InboxItemOut] = []
    q = (search or "").strip().lower()

    channels = {channel} if channel and channel != "all" else None

    if not channels or "email" in channels:
        lead_emails = await db.execute(
            select(LeadEmail, Lead)
            .join(Lead, Lead.id == LeadEmail.lead_id)
            .where(LeadEmail.company_id == company_id)
            .order_by(LeadEmail.sent_at.desc())
            .limit(limit)
        )
        for email, lead in lead_emails.all():
            if range_start and email.sent_at < range_start:
                continue
            if range_end and email.sent_at > range_end:
                continue
            title = email.subject
            preview = _preview(email.body)
            if q and q not in f"{title} {preview} {lead.name}".lower():
                continue
            items.append(
                _item(
                    key=f"email:lead:{email.id}",
                    channel="email",
                    channel_label="Email",
                    title=title,
                    preview=preview,
                    created_at=email.sent_at,
                    link_path=f"/leads/{lead.id}",
                    read_keys=read_keys,
                    contact_name=lead.name,
                    status=email.open_status if email.open_status != "unknown" else email.delivery_status,
                    delivery_status=email.delivery_status,
                    sender_name=await _user_name(db, email.sent_by_id),
                    lead_id=lead.id,
                    metadata={"to": email.to_email, "from": email.from_email},
                )
            )

        deal_emails = await db.execute(
            select(DealEmail, Deal)
            .join(Deal, Deal.id == DealEmail.deal_id)
            .where(DealEmail.company_id == company_id)
            .order_by(DealEmail.sent_at.desc())
            .limit(limit)
        )
        for email, deal in deal_emails.all():
            if range_start and email.sent_at < range_start:
                continue
            if range_end and email.sent_at > range_end:
                continue
            title = email.subject
            preview = _preview(email.body)
            if q and q not in f"{title} {preview} {deal.title}".lower():
                continue
            items.append(
                _item(
                    key=f"email:deal:{email.id}",
                    channel="email",
                    channel_label="Email",
                    title=title,
                    preview=preview,
                    created_at=email.sent_at,
                    link_path=f"/deals/{deal.id}",
                    read_keys=read_keys,
                    contact_name=deal.contact_name or deal.title,
                    status=email.open_status if email.open_status != "unknown" else email.delivery_status,
                    delivery_status=email.delivery_status,
                    sender_name=await _user_name(db, email.sent_by_id),
                    deal_id=deal.id,
                    metadata={"to": email.to_email},
                )
            )

    if not channels or "messaging" in channels or "whatsapp" in channels:
        sms_rows = await db.execute(
            select(SmsLog)
            .where(SmsLog.company_id == company_id)
            .order_by(SmsLog.sent_at.desc())
            .limit(limit)
        )
        for sms in sms_rows.scalars().all():
            if range_start and sms.sent_at < range_start:
                continue
            if range_end and sms.sent_at > range_end:
                continue
            preview = _preview(sms.message)
            if q and q not in f"{preview} {sms.phone}".lower():
                continue
            link = "/inbox"
            contact = sms.phone
            if sms.lead_id:
                lead = await db.get(Lead, sms.lead_id)
                link = f"/leads/{sms.lead_id}"
                contact = lead.name if lead else sms.phone
            elif sms.deal_id:
                link = f"/deals/{sms.deal_id}"
            items.append(
                _item(
                    key=f"sms:{sms.id}",
                    channel="messaging",
                    channel_label="WhatsApp (SMS proxy)",
                    title="Message sent",
                    preview=preview,
                    created_at=sms.sent_at,
                    link_path=link,
                    read_keys=read_keys,
                    contact_name=contact,
                    status=sms.read_status if sms.read_status != "unknown" else sms.status,
                    delivery_status=sms.status,
                    is_proxy=True,
                    sender_name=await _user_name(db, sms.sent_by_id),
                    lead_id=sms.lead_id,
                    deal_id=sms.deal_id,
                    client_id=sms.client_id,
                    metadata={"phone": sms.phone, "proxy": "sms"},
                )
            )

        if settings.whatsapp_enabled:
            wa_rows = await db.execute(
                select(WhatsAppLog)
                .where(WhatsAppLog.company_id == company_id)
                .order_by(WhatsAppLog.sent_at.desc())
                .limit(limit)
            )
            for wa in wa_rows.scalars().all():
                if range_start and wa.sent_at < range_start:
                    continue
                if range_end and wa.sent_at > range_end:
                    continue
                preview = _preview(wa.message)
                if q and q not in preview.lower():
                    continue
                items.append(
                    _item(
                        key=f"whatsapp:{wa.id}",
                        channel="messaging",
                        channel_label="WhatsApp",
                        title="WhatsApp message",
                        preview=preview,
                        created_at=wa.sent_at,
                        link_path=f"/clients/{wa.client_id}" if wa.client_id else "/inbox",
                        read_keys=read_keys,
                        contact_name=wa.phone,
                        status=wa.status,
                        delivery_status=wa.status,
                        is_proxy=False,
                        client_id=wa.client_id,
                    )
                )

    if not channels or "call" in channels:
        lead_calls = await db.execute(
            select(LeadActivity, Lead)
            .join(Lead, Lead.id == LeadActivity.lead_id)
            .where(
                LeadActivity.company_id == company_id,
                LeadActivity.activity_type == "call",
            )
            .order_by(LeadActivity.created_at.desc())
            .limit(limit)
        )
        for act, lead in lead_calls.all():
            ts = act.scheduled_at or act.completed_at or act.created_at
            if range_start and ts < range_start:
                continue
            if range_end and ts > range_end:
                continue
            title = act.title or f"Call — {lead.name}"
            if q and q not in f"{title} {lead.name}".lower():
                continue
            items.append(
                _item(
                    key=f"call:lead:{act.id}",
                    channel="call",
                    channel_label="Call",
                    title=title,
                    preview=_preview(act.notes or "Scheduled call"),
                    created_at=ts,
                    link_path=f"/leads/{lead.id}",
                    read_keys=read_keys,
                    contact_name=lead.name,
                    status="completed" if act.is_completed else "scheduled",
                    lead_id=lead.id,
                )
            )

        deal_calls = await db.execute(
            select(DealActivity, Deal)
            .join(Deal, Deal.id == DealActivity.deal_id)
            .where(
                DealActivity.company_id == company_id,
                DealActivity.activity_type == "call",
            )
            .order_by(DealActivity.created_at.desc())
            .limit(limit)
        )
        for act, deal in deal_calls.all():
            ts = act.scheduled_at or act.completed_at or act.created_at
            if range_start and ts < range_start:
                continue
            if range_end and ts > range_end:
                continue
            title = act.title or f"Call — {deal.title}"
            if q and q not in title.lower():
                continue
            items.append(
                _item(
                    key=f"call:deal:{act.id}",
                    channel="call",
                    channel_label="Call",
                    title=title,
                    preview=_preview(act.notes or "Scheduled call"),
                    created_at=ts,
                    link_path=f"/deals/{deal.id}",
                    read_keys=read_keys,
                    contact_name=deal.contact_name or deal.title,
                    status="completed" if act.is_completed else "scheduled",
                    deal_id=deal.id,
                )
            )

    if not channels or "notification" in channels:
        lead_tl = await db.execute(
            select(LeadTimeline)
            .where(
                LeadTimeline.company_id == company_id,
                LeadTimeline.event_type.in_(NOTIFICATION_EVENTS),
            )
            .order_by(LeadTimeline.created_at.desc())
            .limit(limit)
        )
        for entry in lead_tl.scalars().all():
            if range_start and entry.created_at < range_start:
                continue
            if range_end and entry.created_at > range_end:
                continue
            if q and q not in entry.description.lower():
                continue
            items.append(
                _item(
                    key=f"notification:lead_tl:{entry.id}",
                    channel="notification",
                    channel_label="Notification",
                    title=entry.event_type.replace("_", " ").title(),
                    preview=entry.description,
                    created_at=entry.created_at,
                    link_path=f"/leads/{entry.lead_id}",
                    read_keys=read_keys,
                    lead_id=entry.lead_id,
                    metadata=entry.meta,
                )
            )

        deal_tl = await db.execute(
            select(DealTimeline)
            .where(
                DealTimeline.company_id == company_id,
                DealTimeline.event_type.in_(NOTIFICATION_EVENTS),
            )
            .order_by(DealTimeline.created_at.desc())
            .limit(limit)
        )
        for entry in deal_tl.scalars().all():
            if range_start and entry.created_at < range_start:
                continue
            if range_end and entry.created_at > range_end:
                continue
            if q and q not in entry.description.lower():
                continue
            items.append(
                _item(
                    key=f"notification:deal_tl:{entry.id}",
                    channel="notification",
                    channel_label="Notification",
                    title=entry.event_type.replace("_", " ").title(),
                    preview=entry.description,
                    created_at=entry.created_at,
                    link_path=f"/deals/{entry.deal_id}",
                    read_keys=read_keys,
                    deal_id=entry.deal_id,
                    metadata=entry.meta,
                )
            )

        paid_invoices = await db.execute(
            select(Invoice)
            .where(
                Invoice.company_id == company_id,
                Invoice.status == "paid",
                Invoice.paid_at.isnot(None),
            )
            .order_by(Invoice.paid_at.desc())
            .limit(20)
        )
        for inv in paid_invoices.scalars().all():
            ts = inv.paid_at
            if not ts:
                continue
            if range_start and ts < range_start:
                continue
            if range_end and ts > range_end:
                continue
            title = f"Payment received — {inv.invoice_number}"
            if q and q not in title.lower():
                continue
            items.append(
                _item(
                    key=f"notification:invoice_paid:{inv.id}",
                    channel="notification",
                    channel_label="Notification",
                    title="Invoice paid",
                    preview=title,
                    created_at=ts,
                    link_path=f"/invoices/{inv.id}",
                    read_keys=read_keys,
                    invoice_id=inv.id,
                    client_id=inv.client_id,
                )
            )

        recent_tasks = await db.execute(
            select(Task)
            .where(Task.company_id == company_id)
            .order_by(Task.created_at.desc())
            .limit(20)
        )
        for task in recent_tasks.scalars().all():
            if range_start and task.created_at < range_start:
                continue
            if range_end and task.created_at > range_end:
                continue
            title = f"Task assigned — {task.title}"
            if q and q not in title.lower():
                continue
            items.append(
                _item(
                    key=f"notification:task:{task.id}",
                    channel="notification",
                    channel_label="Notification",
                    title="Task assigned",
                    preview=task.title,
                    created_at=task.created_at,
                    link_path=f"/tasks/{task.id}",
                    read_keys=read_keys,
                    project_id=task.project_id,
                    metadata={"priority": task.priority},
                )
            )

    if not channels or "internal_comment" in channels:
        comments = await db.execute(
            select(InternalComment)
            .where(InternalComment.company_id == company_id)
            .order_by(InternalComment.created_at.desc())
            .limit(limit)
        )
        for comment in comments.scalars().all():
            if range_start and comment.created_at < range_start:
                continue
            if range_end and comment.created_at > range_end:
                continue
            author = await _user_name(db, comment.author_id)
            preview = _preview(comment.body)
            if q and q not in f"{preview} {author or ''}".lower():
                continue
            link = "/inbox"
            if comment.lead_id:
                link = f"/leads/{comment.lead_id}"
            elif comment.deal_id:
                link = f"/deals/{comment.deal_id}"
            elif comment.client_id:
                link = f"/clients/{comment.client_id}"
            items.append(
                _item(
                    key=f"comment:{comment.id}",
                    channel="internal_comment",
                    channel_label="Internal comment",
                    title=f"Comment from {author or 'Team'}",
                    preview=preview,
                    created_at=comment.created_at,
                    link_path=link,
                    read_keys=read_keys,
                    sender_name=author,
                    lead_id=comment.lead_id,
                    deal_id=comment.deal_id,
                    client_id=comment.client_id,
                    project_id=comment.project_id,
                    invoice_id=comment.invoice_id,
                    metadata={"internal": True},
                )
            )

    items.sort(key=lambda i: i.created_at, reverse=True)
    if unread_only:
        items = [i for i in items if i.read_status == "unread"]
    return items[:limit]


async def build_inbox_summary(
    db: AsyncSession,
    company_id: UUID,
    user_id: UUID,
) -> InboxSummary:
    items = await fetch_inbox_items(db, company_id, user_id, limit=200)
    unread = sum(1 for i in items if i.read_status == "unread")

    today_end = datetime.combine(date.today(), time.max, tzinfo=UTC)
    followups = await db.execute(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.next_followup.isnot(None),
            Lead.next_followup <= today_end,
            Lead.status.not_in(("won", "lost")),
        )
    )
    pending_followups = len(list(followups.scalars().all()))

    overdue = await db.execute(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status.in_(("unpaid", "overdue")),
            Invoice.due_date < date.today(),
        )
    )
    overdue_count = len(list(overdue.scalars().all()))

    proposals = await db.execute(
        select(Deal).where(
            Deal.company_id == company_id,
            Deal.status == "proposal_sent",
        )
    )
    proposal_count = len(list(proposals.scalars().all()))

    high_priority = sum(
        1
        for i in items
        if i.read_status == "unread"
        and i.channel in ("email", "messaging", "internal_comment")
    )

    lines: list[str] = []
    if unread:
        lines.append(f"{unread} unread message(s)")
    if pending_followups:
        lines.append(f"{pending_followups} pending follow-up(s)")
    if overdue_count:
        lines.append(f"{overdue_count} overdue invoice(s)")
    if proposal_count:
        lines.append(f"{proposal_count} proposal(s) awaiting response")
    if not lines:
        lines.append("Inbox is up to date")

    return InboxSummary(
        unread_messages=unread,
        pending_followups=pending_followups,
        overdue_invoices=overdue_count,
        proposals_needing_revision=proposal_count,
        high_priority_count=high_priority,
        summary_lines=lines,
    )


def date_filter_range(filter_name: str | None) -> tuple[datetime | None, datetime | None]:
    if not filter_name or filter_name == "all":
        return None, None
    today = date.today()
    if filter_name == "today":
        return datetime.combine(today, time.min, tzinfo=UTC), datetime.combine(today, time.max, tzinfo=UTC)
    if filter_name == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return datetime.combine(start, time.min, tzinfo=UTC), datetime.combine(end, time.max, tzinfo=UTC)
    return None, None
