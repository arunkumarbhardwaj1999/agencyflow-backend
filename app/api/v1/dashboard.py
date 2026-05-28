from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_permission
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.project import Project
from app.models.task import Task
from app.schemas.dashboard import ActivityEvent, DashboardKPIs, DashboardResponse, UpcomingDeadline

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current: CurrentUser = Depends(require_permission("view_analytics")),
    db: AsyncSession = Depends(get_db),
):
    cid = current.company_id

    open_leads = await db.execute(
        select(func.count()).select_from(Lead).where(Lead.company_id == cid, Lead.status.notin_(["won", "lost"]))
    )
    active_projects = await db.execute(
        select(func.count()).select_from(Project).where(
            Project.company_id == cid, Project.status.in_(["planning", "active", "review"])
        )
    )
    paid_invoices = await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.company_id == cid, Invoice.status == "paid")
    )
    unpaid_total = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status.in_(["unpaid", "overdue"])
        )
    )
    pipeline_value = await db.execute(
        select(func.coalesce(func.sum(Lead.value), 0)).where(
            Lead.company_id == cid, Lead.status.notin_(["won", "lost"])
        )
    )

    kpis = DashboardKPIs(
        open_leads=open_leads.scalar_one(),
        active_projects=active_projects.scalar_one(),
        paid_invoices=paid_invoices.scalar_one(),
        unpaid_invoice_total=Decimal(str(unpaid_total.scalar_one())),
        pipeline_value=Decimal(str(pipeline_value.scalar_one())),
    )

    now = datetime.now(UTC)
    task_deadlines = await db.execute(
        select(Task)
        .where(
            Task.company_id == cid,
            Task.due_date.isnot(None),
            Task.due_date >= now,
            Task.status != "done",
        )
        .order_by(Task.due_date.asc())
        .limit(5)
    )
    lead_followups = await db.execute(
        select(Lead)
        .where(Lead.company_id == cid, Lead.next_followup.isnot(None), Lead.next_followup >= now)
        .order_by(Lead.next_followup.asc())
        .limit(5)
    )

    deadlines: list[UpcomingDeadline] = []
    for t in task_deadlines.scalars():
        if t.due_date is not None:
            deadlines.append(
                UpcomingDeadline(id=t.id, type="task", title=t.title, due_at=t.due_date)
            )
    for lead in lead_followups.scalars():
        if lead.next_followup is not None:
            deadlines.append(
                UpcomingDeadline(id=lead.id, type="lead", title=lead.name, due_at=lead.next_followup)
            )
    deadlines.sort(key=lambda d: d.due_at)
    deadlines = deadlines[:8]

    recent_leads = await db.execute(
        select(Lead).where(Lead.company_id == cid).order_by(Lead.created_at.desc()).limit(5)
    )
    activity: list[ActivityEvent] = []
    for lead in recent_leads.scalars():
        activity.append(
            ActivityEvent(
                id=f"lead-{lead.id}",
                type="lead",
                message=f"Lead '{lead.name}' — {lead.status}",
                created_at=lead.created_at,
            )
        )
    for ev in realtime_manager.recent(cid, limit=5):
        activity.append(
            ActivityEvent(
                id=ev["id"],
                type=ev["type"],
                message=ev["message"],
                created_at=datetime.fromisoformat(ev["created_at"]),
            )
        )
    activity.sort(key=lambda item: item.created_at, reverse=True)
    activity = activity[:8]

    return DashboardResponse(kpis=kpis, upcoming_deadlines=deadlines, recent_activity=activity)
