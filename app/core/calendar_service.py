"""Aggregate calendar events from leads, deals, tasks, projects, and invoices."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from app.core.utc import UTC
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar_types import ACTIVITY_TYPE_MAP, calendar_color, calendar_icon
from app.models.client import Client
from app.models.contract import Contract
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.calendar import CalendarAgendaItem, CalendarEventOut, CalendarTodayAgenda


def _utc_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def _utc_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=UTC)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _in_range(starts: datetime, range_start: datetime, range_end: datetime) -> bool:
    return range_start <= starts <= range_end


def _event(
    *,
    key: str,
    title: str,
    event_type: str,
    starts_at: datetime,
    source_type: str,
    source_id: UUID,
    link_path: str,
    ends_at: datetime | None = None,
    all_day: bool = False,
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    project_id: UUID | None = None,
    invoice_id: UUID | None = None,
    task_id: UUID | None = None,
    assigned_to_id: UUID | None = None,
    assigned_to_name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int = 0,
) -> CalendarEventOut:
    start = _ensure_aware(starts_at)
    end = _ensure_aware(ends_at) if ends_at else (start + timedelta(hours=1) if not all_day else None)
    return CalendarEventOut(
        id=key,
        title=title,
        event_type=event_type,
        color=calendar_color(event_type),
        icon=calendar_icon(event_type),
        starts_at=start,
        ends_at=end,
        all_day=all_day,
        source_type=source_type,
        source_id=source_id,
        lead_id=lead_id,
        deal_id=deal_id,
        project_id=project_id,
        invoice_id=invoice_id,
        task_id=task_id,
        assigned_to_id=assigned_to_id,
        assigned_to_name=assigned_to_name,
        description=description,
        status=status,
        link_path=link_path,
        priority=priority,
    )


async def _user_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


def view_date_range(view: str, anchor: date) -> tuple[datetime, datetime]:
    if view == "day":
        return _utc_start(anchor), _utc_end(anchor)
    if view == "week":
        week_start = anchor - timedelta(days=anchor.weekday())
        week_end = week_start + timedelta(days=6)
        return _utc_start(week_start), _utc_end(week_end)
    # month (default)
    month_start = anchor.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    month_end = next_month - timedelta(days=1)
    pad_start = month_start - timedelta(days=month_start.weekday())
    pad_end = month_end + timedelta(days=(6 - month_end.weekday()))
    return _utc_start(pad_start), _utc_end(pad_end)


async def fetch_calendar_events(
    db: AsyncSession,
    company_id: UUID,
    range_start: datetime,
    range_end: datetime,
    *,
    assigned_to_id: UUID | None = None,
) -> list[CalendarEventOut]:
    events: list[CalendarEventOut] = []

    lead_act_q = select(LeadActivity, Lead).join(Lead, Lead.id == LeadActivity.lead_id).where(
        LeadActivity.company_id == company_id,
        LeadActivity.is_completed.is_(False),
        LeadActivity.scheduled_at.isnot(None),
        LeadActivity.scheduled_at >= range_start,
        LeadActivity.scheduled_at <= range_end,
    )
    if assigned_to_id:
        lead_act_q = lead_act_q.where(
            or_(LeadActivity.assigned_to_id == assigned_to_id, Lead.assigned_user_id == assigned_to_id)
        )
    for activity, lead in (await db.execute(lead_act_q)).all():
        event_type = ACTIVITY_TYPE_MAP.get(activity.activity_type, "task")
        assignee = activity.assigned_to_id or lead.assigned_user_id
        events.append(
            _event(
                key=f"lead_activity:{activity.id}",
                title=activity.title or f"{event_type.replace('_', ' ').title()} — {lead.name}",
                event_type=event_type,
                starts_at=activity.scheduled_at,
                source_type="lead_activity",
                source_id=activity.id,
                link_path=f"/leads/{lead.id}",
                lead_id=lead.id,
                assigned_to_id=assignee,
                description=activity.notes,
                status=activity.activity_type,
                priority=3 if event_type == "meeting" else 2,
            )
        )

    deal_act_q = select(DealActivity, Deal).join(Deal, Deal.id == DealActivity.deal_id).where(
        DealActivity.company_id == company_id,
        DealActivity.is_completed.is_(False),
        DealActivity.scheduled_at.isnot(None),
        DealActivity.scheduled_at >= range_start,
        DealActivity.scheduled_at <= range_end,
    )
    if assigned_to_id:
        deal_act_q = deal_act_q.where(
            or_(DealActivity.assigned_to_id == assigned_to_id, Deal.assigned_user_id == assigned_to_id)
        )
    for activity, deal in (await db.execute(deal_act_q)).all():
        event_type = ACTIVITY_TYPE_MAP.get(activity.activity_type, "task")
        assignee = activity.assigned_to_id or deal.assigned_user_id
        events.append(
            _event(
                key=f"deal_activity:{activity.id}",
                title=activity.title or f"{event_type.replace('_', ' ').title()} — {deal.title}",
                event_type=event_type,
                starts_at=activity.scheduled_at,
                source_type="deal_activity",
                source_id=activity.id,
                link_path=f"/deals/{deal.id}",
                deal_id=deal.id,
                assigned_to_id=assignee,
                description=activity.notes,
                status=activity.activity_type,
                priority=3 if event_type == "meeting" else 2,
            )
        )

    lead_follow_q = select(Lead).where(
        Lead.company_id == company_id,
        Lead.next_followup.isnot(None),
        Lead.next_followup >= range_start,
        Lead.next_followup <= range_end,
        Lead.status.not_in(("won", "lost")),
    )
    if assigned_to_id:
        lead_follow_q = lead_follow_q.where(Lead.assigned_user_id == assigned_to_id)
    for lead in (await db.execute(lead_follow_q)).scalars().all():
        events.append(
            _event(
                key=f"lead_followup:{lead.id}",
                title=f"Follow-up — {lead.name}",
                event_type="lead_followup",
                starts_at=lead.next_followup,
                source_type="lead",
                source_id=lead.id,
                link_path=f"/leads/{lead.id}",
                lead_id=lead.id,
                assigned_to_id=lead.assigned_user_id,
                description=lead.company_name,
                status=lead.status,
                priority=4,
            )
        )

    deal_close_q = select(Deal).where(
        Deal.company_id == company_id,
        Deal.expected_close_date.isnot(None),
        Deal.status.not_in(("won", "lost")),
    )
    if assigned_to_id:
        deal_close_q = deal_close_q.where(Deal.assigned_user_id == assigned_to_id)
    for deal in (await db.execute(deal_close_q)).scalars().all():
        starts = _utc_start(deal.expected_close_date)
        if _in_range(starts, range_start, range_end):
            events.append(
                _event(
                    key=f"deal_close:{deal.id}",
                    title=f"Deal close — {deal.title}",
                    event_type="deal_close",
                    starts_at=starts,
                    all_day=True,
                    source_type="deal",
                    source_id=deal.id,
                    link_path=f"/deals/{deal.id}",
                    deal_id=deal.id,
                    assigned_to_id=deal.assigned_user_id,
                    description=deal.company_name,
                    status=deal.status,
                    priority=5,
                )
            )

    task_q = select(Task).where(
        Task.company_id == company_id,
        Task.due_date.isnot(None),
        Task.due_date >= range_start,
        Task.due_date <= range_end,
        Task.status != "done",
    )
    if assigned_to_id:
        task_q = task_q.where(Task.assigned_to == assigned_to_id)
    for task in (await db.execute(task_q)).scalars().all():
        prio = {"urgent": 6, "high": 5, "medium": 3, "low": 1}.get(task.priority, 2)
        events.append(
            _event(
                key=f"task:{task.id}",
                title=task.title,
                event_type="task",
                starts_at=task.due_date,
                source_type="task",
                source_id=task.id,
                link_path=f"/tasks/{task.id}",
                task_id=task.id,
                project_id=task.project_id,
                assigned_to_id=task.assigned_to,
                description=task.description,
                status=task.status,
                priority=prio,
            )
        )

    project_q = select(Project).where(
        Project.company_id == company_id,
        Project.end_date.isnot(None),
        Project.status.not_in(("completed", "cancelled")),
    )
    for project in (await db.execute(project_q)).scalars().all():
        starts = _utc_start(project.end_date)
        if _in_range(starts, range_start, range_end):
            events.append(
                _event(
                    key=f"project_deadline:{project.id}",
                    title=f"Project deadline — {project.title}",
                    event_type="project_deadline",
                    starts_at=starts,
                    all_day=True,
                    source_type="project",
                    source_id=project.id,
                    link_path=f"/projects/{project.id}",
                    project_id=project.id,
                    description=project.description,
                    status=project.status,
                    priority=5,
                )
            )

    invoice_q = select(Invoice).where(
        Invoice.company_id == company_id,
        Invoice.status.in_(("unpaid", "overdue")),
    )
    for invoice in (await db.execute(invoice_q)).scalars().all():
        starts = _utc_start(invoice.due_date)
        if _in_range(starts, range_start, range_end):
            prio = 7 if invoice.status == "overdue" else 5
            events.append(
                _event(
                    key=f"invoice_due:{invoice.id}",
                    title=f"Invoice due — {invoice.invoice_number}",
                    event_type="invoice_due",
                    starts_at=starts,
                    all_day=True,
                    source_type="invoice",
                    source_id=invoice.id,
                    link_path=f"/invoices/{invoice.id}",
                    invoice_id=invoice.id,
                    status=invoice.status,
                    priority=prio,
                )
            )

    contract_q = select(Contract).where(
        Contract.company_id == company_id,
        Contract.status.in_(("signed", "active")),
        Contract.expires_at.is_not(None),
    )
    for contract in (await db.execute(contract_q)).scalars().all():
        starts = _utc_start(contract.expires_at)
        if _in_range(starts, range_start, range_end):
            client = await db.get(Client, contract.client_id)
            client_label = client.business_name if client else "Client"
            events.append(
                _event(
                    key=f"contract_expiry:{contract.id}",
                    title=f"Contract expires — {client_label}",
                    event_type="contract_expiry",
                    starts_at=starts,
                    all_day=True,
                    source_type="contract",
                    source_id=contract.id,
                    link_path=f"/contracts/{contract.id}",
                    description=contract.title,
                    status=contract.status,
                    priority=6,
                )
            )

    for event in events:
        if event.assigned_to_id and not event.assigned_to_name:
            event.assigned_to_name = await _user_name(db, event.assigned_to_id)

    events.sort(key=lambda e: (e.starts_at, -e.priority))
    return events


def build_today_agenda(
    events: list[CalendarEventOut],
    *,
    user_name: str,
    today: date,
) -> CalendarTodayAgenda:
    today_start = _utc_start(today)
    today_end = _utc_end(today)

    today_events = [e for e in events if today_start <= e.starts_at <= today_end]
    today_events.sort(key=lambda e: (e.starts_at, -e.priority))

    priorities: list[CalendarAgendaItem] = []
    seen: set[str] = set()

    def add_priority(event: CalendarEventOut, reason: str) -> None:
        if event.id in seen:
            return
        seen.add(event.id)
        priorities.append(CalendarAgendaItem(event=event, reason=reason))

    for event in sorted(events, key=lambda e: -e.priority):
        if event.event_type == "invoice_due" and event.status == "overdue":
            add_priority(event, "Overdue invoice — collect payment")
        elif event.event_type == "meeting" and event.starts_at.date() == today:
            add_priority(event, f"Meeting at {event.starts_at.strftime('%I:%M %p')}")
        elif event.event_type == "call" and event.starts_at.date() == today:
            add_priority(event, f"Call scheduled at {event.starts_at.strftime('%I:%M %p')}")
        elif event.event_type == "lead_followup" and event.starts_at.date() == today:
            add_priority(event, "Lead follow-up due today")
        elif event.event_type == "deal_close" and event.starts_at.date() == today:
            add_priority(event, "Deal expected to close today")
        elif event.event_type == "task" and event.starts_at.date() == today:
            add_priority(event, "Task due today")
        elif event.event_type == "project_deadline" and event.starts_at.date() == today:
            add_priority(event, "Project deadline today")

    tomorrow = today + timedelta(days=1)
    for event in events:
        if event.event_type == "proposal" and event.starts_at.date() == tomorrow:
            add_priority(event, "Proposal deadline tomorrow")

    for event in today_events:
        if event.id not in seen and event.event_type == "invoice_due":
            add_priority(event, "Invoice due today")

    summary_parts = [f"{len(today_events)} event(s) today"]
    if priorities:
        summary_parts.append(f"{len(priorities)} priority item(s)")

    first_name = user_name.split()[0] if user_name else "there"
    hour = datetime.now(UTC).hour
    if hour < 12:
        greeting = f"Good morning, {first_name}"
    elif hour < 17:
        greeting = f"Good afternoon, {first_name}"
    else:
        greeting = f"Good evening, {first_name}"

    return CalendarTodayAgenda(
        greeting=greeting,
        user_name=user_name,
        date=today,
        priorities=priorities[:8],
        events_today=today_events,
        summary=" · ".join(summary_parts),
    )
