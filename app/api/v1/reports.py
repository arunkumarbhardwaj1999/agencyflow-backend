from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, require_permission
from app.core.time_utils import format_duration
from app.db.session import get_db
from app.models.deal import Deal
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.portal import ClientApproval
from app.models.project import Project
from app.models.project_expense import ProjectExpense
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["reports"])

OPEN_DEAL_STATUSES = ("qualification", "proposal_sent", "negotiation")
ACTIVE_PROJECT_STATUSES = ("planning", "active", "review")


class TeamMemberProductivity(BaseModel):
    user_id: UUID
    name: str
    role: str
    tasks_done: int
    tasks_open: int
    hours_logged_label: str
    hours_logged_seconds: int


class LeadConversionReport(BaseModel):
    total_leads: int
    open_leads: int
    won: int
    lost: int
    conversion_rate: float
    by_status: dict[str, int]


class ProjectStatusReport(BaseModel):
    planning: int
    active: int
    review: int
    completed: int
    total: int


class ManagerReportsOut(BaseModel):
    team_productivity: list[TeamMemberProductivity]
    lead_conversion: LeadConversionReport
    project_status: ProjectStatusReport
    open_deals: int
    deal_pipeline_value: Decimal
    revenue_paid: Decimal
    revenue_outstanding: Decimal
    pending_approvals: int


class ManagerDashboardOut(BaseModel):
    open_leads: int
    open_deals: int
    active_projects: int
    pending_approvals: int
    pipeline_value: Decimal
    deal_pipeline_value: Decimal
    revenue_paid: Decimal
    revenue_outstanding: Decimal
    team_size: int
    tasks_done_this_week: int
    tasks_open: int
    avg_project_progress: int


@router.get("/manager", response_model=ManagerReportsOut)
async def manager_reports(
    current: CurrentUser = Depends(require_permission("view_analytics")),
    db: AsyncSession = Depends(get_db),
):
    cid = current.company_id
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)

    members = await _staff_members(db, cid)
    productivity: list[TeamMemberProductivity] = []
    for member in members:
        done = await db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.company_id == cid,
                Task.assigned_to == member.id,
                Task.status == "done",
            )
        )
        open_tasks = await db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.company_id == cid,
                Task.assigned_to == member.id,
                Task.status != "done",
            )
        )
        secs = await _hours_since(db, cid, member.id, week_start_dt)
        role_name = member.role.name if member.role else "employee"
        productivity.append(
            TeamMemberProductivity(
                user_id=member.id,
                name=f"{member.first_name} {member.last_name or ''}".strip(),
                role=role_name,
                tasks_done=int(done.scalar_one() or 0),
                tasks_open=int(open_tasks.scalar_one() or 0),
                hours_logged_seconds=secs,
                hours_logged_label=format_duration(secs),
            )
        )
    productivity.sort(key=lambda m: (-m.tasks_done, -m.hours_logged_seconds))

    leads = (
        await db.execute(select(Lead.status).where(Lead.company_id == cid))
    ).scalars().all()
    by_status: dict[str, int] = {}
    for status in leads:
        by_status[status] = by_status.get(status, 0) + 1
    won = by_status.get("won", 0)
    lost = by_status.get("lost", 0)
    decided = won + lost
    conversion = round((won / decided) * 100, 1) if decided else 0.0
    open_leads = sum(c for s, c in by_status.items() if s not in ("won", "lost"))

    projects = (
        await db.execute(select(Project.status).where(Project.company_id == cid))
    ).scalars().all()
    project_status = ProjectStatusReport(
        planning=sum(1 for s in projects if s == "planning"),
        active=sum(1 for s in projects if s == "active"),
        review=sum(1 for s in projects if s == "review"),
        completed=sum(1 for s in projects if s == "completed"),
        total=len(projects),
    )

    open_deals = await db.execute(
        select(func.count())
        .select_from(Deal)
        .where(Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES))
    )
    deal_pipeline = await db.execute(
        select(func.coalesce(func.sum(Deal.value), 0)).where(
            Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES)
        )
    )
    paid = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status == "paid"
        )
    )
    outstanding = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status.in_(["unpaid", "overdue"])
        )
    )
    pending = await db.execute(
        select(func.count())
        .select_from(ClientApproval)
        .where(ClientApproval.company_id == cid, ClientApproval.status == "pending")
    )

    return ManagerReportsOut(
        team_productivity=productivity,
        lead_conversion=LeadConversionReport(
            total_leads=len(leads),
            open_leads=open_leads,
            won=won,
            lost=lost,
            conversion_rate=conversion,
            by_status=by_status,
        ),
        project_status=project_status,
        open_deals=int(open_deals.scalar_one() or 0),
        deal_pipeline_value=Decimal(str(deal_pipeline.scalar_one())),
        revenue_paid=Decimal(str(paid.scalar_one())),
        revenue_outstanding=Decimal(str(outstanding.scalar_one())),
        pending_approvals=int(pending.scalar_one() or 0),
    )


@router.get("/manager/dashboard", response_model=ManagerDashboardOut)
async def manager_dashboard(
    current: CurrentUser = Depends(require_permission("view_analytics")),
    db: AsyncSession = Depends(get_db),
):
    cid = current.company_id
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)

    open_leads = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.company_id == cid, Lead.status.notin_(["won", "lost"]))
    )
    open_deals = await db.execute(
        select(func.count())
        .select_from(Deal)
        .where(Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES))
    )
    active_projects_q = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.company_id == cid, Project.status.in_(ACTIVE_PROJECT_STATUSES))
    )
    active_projects = list(active_projects_q.scalars().all())
    progresses = []
    for p in active_projects:
        tasks = p.tasks or []
        if tasks:
            progresses.append(int(sum(1 for t in tasks if t.status == "done") / len(tasks) * 100))
        else:
            progresses.append(0)
    avg_progress = int(sum(progresses) / len(progresses)) if progresses else 0

    pending = await db.execute(
        select(func.count())
        .select_from(ClientApproval)
        .where(ClientApproval.company_id == cid, ClientApproval.status == "pending")
    )
    pipeline = await db.execute(
        select(func.coalesce(func.sum(Lead.value), 0)).where(
            Lead.company_id == cid, Lead.status.notin_(["won", "lost"])
        )
    )
    deal_pipeline = await db.execute(
        select(func.coalesce(func.sum(Deal.value), 0)).where(
            Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES)
        )
    )
    paid = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status == "paid"
        )
    )
    outstanding = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status.in_(["unpaid", "overdue"])
        )
    )
    members = await _staff_members(db, cid)
    tasks_done_week = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(
            Task.company_id == cid,
            Task.status == "done",
            Task.created_at >= week_start_dt,
        )
    )
    # Prefer updated tasks this week — without updated_at, approximate via done count company-wide open
    tasks_open = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.company_id == cid, Task.status != "done")
    )

    return ManagerDashboardOut(
        open_leads=int(open_leads.scalar_one() or 0),
        open_deals=int(open_deals.scalar_one() or 0),
        active_projects=len(active_projects),
        pending_approvals=int(pending.scalar_one() or 0),
        pipeline_value=Decimal(str(pipeline.scalar_one())),
        deal_pipeline_value=Decimal(str(deal_pipeline.scalar_one())),
        revenue_paid=Decimal(str(paid.scalar_one())),
        revenue_outstanding=Decimal(str(outstanding.scalar_one())),
        team_size=len(members),
        tasks_done_this_week=int(tasks_done_week.scalar_one() or 0),
        tasks_open=int(tasks_open.scalar_one() or 0),
        avg_project_progress=avg_progress,
    )


class CashFlowMonth(BaseModel):
    month: str
    label: str
    inflow: Decimal
    outflow: Decimal
    net: Decimal


class ExpenseCategoryRow(BaseModel):
    category: str
    label: str
    amount: Decimal


class OwnerExecutiveOut(BaseModel):
    revenue_paid: Decimal
    revenue_outstanding: Decimal
    revenue_invoiced: Decimal
    expenses_total: Decimal
    profit: Decimal
    pipeline_value: Decimal
    deal_pipeline_value: Decimal
    open_leads: int
    open_deals: int
    active_projects: int
    team_size: int
    conversion_rate: float
    cash_flow: list[CashFlowMonth]
    expenses_by_category: list[ExpenseCategoryRow]
    team_productivity: list[TeamMemberProductivity]
    project_status: ProjectStatusReport


@router.get("/owner", response_model=OwnerExecutiveOut)
async def owner_executive(
    current: CurrentUser = Depends(require_permission("view_analytics")),
    db: AsyncSession = Depends(get_db),
):
    """Executive business overview — owners (and anyone with view_analytics)."""
    cid = current.company_id
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)

    paid = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status == "paid"
        )
    )
    outstanding = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.company_id == cid, Invoice.status.in_(["unpaid", "overdue"])
        )
    )
    invoiced = await db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.company_id == cid)
    )
    expenses = await db.execute(
        select(func.coalesce(func.sum(ProjectExpense.amount), 0)).where(
            ProjectExpense.company_id == cid
        )
    )
    revenue_paid = Decimal(str(paid.scalar_one()))
    expenses_total = Decimal(str(expenses.scalar_one()))
    profit = revenue_paid - expenses_total

    pipeline = await db.execute(
        select(func.coalesce(func.sum(Lead.value), 0)).where(
            Lead.company_id == cid, Lead.status.notin_(["won", "lost"])
        )
    )
    deal_pipeline = await db.execute(
        select(func.coalesce(func.sum(Deal.value), 0)).where(
            Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES)
        )
    )
    open_leads = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.company_id == cid, Lead.status.notin_(["won", "lost"]))
    )
    open_deals = await db.execute(
        select(func.count())
        .select_from(Deal)
        .where(Deal.company_id == cid, Deal.status.in_(OPEN_DEAL_STATUSES))
    )
    active_projects = await db.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.company_id == cid, Project.status.in_(ACTIVE_PROJECT_STATUSES))
    )

    leads = (await db.execute(select(Lead.status).where(Lead.company_id == cid))).scalars().all()
    by_status: dict[str, int] = {}
    for status in leads:
        by_status[status] = by_status.get(status, 0) + 1
    won = by_status.get("won", 0)
    lost = by_status.get("lost", 0)
    decided = won + lost
    conversion = round((won / decided) * 100, 1) if decided else 0.0

    projects = (await db.execute(select(Project.status).where(Project.company_id == cid))).scalars().all()
    project_status = ProjectStatusReport(
        planning=sum(1 for s in projects if s == "planning"),
        active=sum(1 for s in projects if s == "active"),
        review=sum(1 for s in projects if s == "review"),
        completed=sum(1 for s in projects if s == "completed"),
        total=len(projects),
    )

    # Cash flow — last 6 calendar months
    today = date.today()
    cash_flow: list[CashFlowMonth] = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1)
        else:
            end = date(y, m + 1, 1)
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC)

        inflow_q = await db.execute(
            select(func.coalesce(func.sum(Invoice.total), 0)).where(
                Invoice.company_id == cid,
                Invoice.status == "paid",
                func.coalesce(Invoice.paid_at, Invoice.created_at) >= start_dt,
                func.coalesce(Invoice.paid_at, Invoice.created_at) < end_dt,
            )
        )
        outflow_q = await db.execute(
            select(func.coalesce(func.sum(ProjectExpense.amount), 0)).where(
                ProjectExpense.company_id == cid,
                ProjectExpense.expense_date >= start,
                ProjectExpense.expense_date < end,
            )
        )
        inflow = Decimal(str(inflow_q.scalar_one()))
        outflow = Decimal(str(outflow_q.scalar_one()))
        cash_flow.append(
            CashFlowMonth(
                month=start.strftime("%Y-%m"),
                label=start.strftime("%b %Y"),
                inflow=inflow,
                outflow=outflow,
                net=inflow - outflow,
            )
        )

    cat_rows = await db.execute(
        select(ProjectExpense.category, func.coalesce(func.sum(ProjectExpense.amount), 0))
        .where(ProjectExpense.company_id == cid)
        .group_by(ProjectExpense.category)
        .order_by(func.sum(ProjectExpense.amount).desc())
    )
    label_map = {
        "hosting": "Hosting",
        "domain": "Domain",
        "travel": "Travel",
        "software": "Software",
        "marketing": "Marketing",
        "printing": "Printing",
        "miscellaneous": "Others",
    }
    expenses_by_category = [
        ExpenseCategoryRow(
            category=cat or "miscellaneous",
            label=label_map.get(cat or "", (cat or "other").replace("_", " ").title()),
            amount=Decimal(str(amt)),
        )
        for cat, amt in cat_rows.all()
    ]

    members = await _staff_members(db, cid)
    productivity: list[TeamMemberProductivity] = []
    for member in members:
        done = await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.company_id == cid, Task.assigned_to == member.id, Task.status == "done")
        )
        open_tasks = await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.company_id == cid, Task.assigned_to == member.id, Task.status != "done")
        )
        secs = await _hours_since(db, cid, member.id, week_start_dt)
        role_name = member.role.name if member.role else "employee"
        productivity.append(
            TeamMemberProductivity(
                user_id=member.id,
                name=f"{member.first_name} {member.last_name or ''}".strip(),
                role=role_name,
                tasks_done=int(done.scalar_one() or 0),
                tasks_open=int(open_tasks.scalar_one() or 0),
                hours_logged_seconds=secs,
                hours_logged_label=format_duration(secs),
            )
        )
    productivity.sort(key=lambda m: (-m.tasks_done, -m.hours_logged_seconds))

    return OwnerExecutiveOut(
        revenue_paid=revenue_paid,
        revenue_outstanding=Decimal(str(outstanding.scalar_one())),
        revenue_invoiced=Decimal(str(invoiced.scalar_one())),
        expenses_total=expenses_total,
        profit=profit,
        pipeline_value=Decimal(str(pipeline.scalar_one())),
        deal_pipeline_value=Decimal(str(deal_pipeline.scalar_one())),
        open_leads=int(open_leads.scalar_one() or 0),
        open_deals=int(open_deals.scalar_one() or 0),
        active_projects=int(active_projects.scalar_one() or 0),
        team_size=len(members),
        conversion_rate=conversion,
        cash_flow=cash_flow,
        expenses_by_category=expenses_by_category,
        team_productivity=productivity,
        project_status=project_status,
    )


class OwnerExpenseRow(BaseModel):
    id: UUID
    project_id: UUID
    project_title: str | None
    category: str
    category_label: str
    title: str
    amount: Decimal
    expense_date: date
    notes: str | None


@router.get("/owner/expenses", response_model=list[OwnerExpenseRow])
async def owner_expenses(
    current: CurrentUser = Depends(require_permission("view_analytics")),
    db: AsyncSession = Depends(get_db),
):
    cid = current.company_id
    result = await db.execute(
        select(ProjectExpense)
        .where(ProjectExpense.company_id == cid)
        .order_by(ProjectExpense.expense_date.desc())
        .limit(100)
    )
    expenses = list(result.scalars().all())
    project_ids = {e.project_id for e in expenses}
    title_map: dict[UUID, str] = {}
    if project_ids:
        rows = await db.execute(select(Project.id, Project.title).where(Project.id.in_(project_ids)))
        title_map = {pid: title for pid, title in rows.all()}
    label_map = {
        "hosting": "Hosting",
        "domain": "Domain",
        "travel": "Travel",
        "software": "Software",
        "marketing": "Marketing",
        "printing": "Printing",
        "miscellaneous": "Others",
    }
    return [
        OwnerExpenseRow(
            id=e.id,
            project_id=e.project_id,
            project_title=title_map.get(e.project_id),
            category=e.category,
            category_label=label_map.get(e.category, e.category.replace("_", " ").title()),
            title=e.title,
            amount=Decimal(str(e.amount or 0)),
            expense_date=e.expense_date,
            notes=e.notes,
        )
        for e in expenses
    ]


async def _staff_members(db: AsyncSession, company_id: UUID) -> list[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.company_id == company_id, User.is_active.is_(True))
        .order_by(User.first_name.asc())
    )
    users = []
    for u in result.scalars().all():
        role = u.role.name if u.role else "employee"
        if role == "client":
            continue
        users.append(u)
    return users


async def _hours_since(db: AsyncSession, company_id: UUID, user_id: UUID, since: datetime) -> int:
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.company_id == company_id,
            TimeEntry.user_id == user_id,
            TimeEntry.started_at >= since,
        )
    )
    total = 0
    now = datetime.now(UTC)
    for entry in result.scalars().all():
        if entry.is_running:
            total += max(0, int((now - entry.started_at).total_seconds()))
        else:
            total += entry.duration_seconds or 0
    return total
