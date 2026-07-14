from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_company
from app.core.time_utils import format_duration, format_duration_clock, format_hours_decimal
from app.db.session import get_db
from app.models.project import Project
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.time_tracking import (
    ActiveTimerOut,
    ProjectTimeSummary,
    TimeEntryOut,
    TimeSummaryPeriod,
    TimerStartRequest,
    UserTimeSummary,
)

router = APIRouter(prefix="/time", tags=["time-tracking"])


@router.get("/timer/active", response_model=ActiveTimerOut)
async def get_active_timer(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    entry = await _running_entry(db, current.company_id, current.id)
    if not entry:
        return ActiveTimerOut(running=False, entry=None, elapsed_seconds=0)
    elapsed = _elapsed_seconds(entry)
    return ActiveTimerOut(
        running=True,
        entry=await _entry_out(db, entry),
        elapsed_seconds=elapsed,
    )


@router.post("/timer/start", response_model=ActiveTimerOut)
async def start_timer(
    body: TimerStartRequest,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, body.task_id, current)
    existing = await _running_entry(db, current.company_id, current.id)
    if existing:
        raise HTTPException(status_code=400, detail="Stop your current timer before starting a new one")

    now = datetime.now(UTC)
    entry = TimeEntry(
        company_id=current.company_id,
        user_id=current.id,
        project_id=task.project_id,
        task_id=task.id,
        started_at=now,
        is_running=True,
        duration_seconds=0,
    )
    db.add(entry)
    await db.flush()
    return ActiveTimerOut(running=True, entry=await _entry_out(db, entry), elapsed_seconds=0)


@router.post("/timer/stop", response_model=TimeEntryOut)
async def stop_timer(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    entry = await _running_entry(db, current.company_id, current.id)
    if not entry:
        raise HTTPException(status_code=400, detail="No running timer")

    now = datetime.now(UTC)
    entry.ended_at = now
    entry.is_running = False
    entry.duration_seconds = max(0, int((now - entry.started_at).total_seconds()))
    await db.flush()
    return await _entry_out(db, entry)


@router.get("/entries", response_model=list[TimeEntryOut])
async def list_time_entries(
    task_id: UUID | None = None,
    project_id: UUID | None = None,
    user_id: UUID | None = None,
    limit: int = Query(default=50, le=200),
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    q = select(TimeEntry).where(TimeEntry.company_id == current.company_id)
    if current.role_name == "employee" and not current.can("manage_tasks"):
        q = q.where(TimeEntry.user_id == current.id)
    elif user_id:
        q = q.where(TimeEntry.user_id == user_id)
    if task_id:
        q = q.where(TimeEntry.task_id == task_id)
    if project_id:
        q = q.where(TimeEntry.project_id == project_id)
    q = q.order_by(TimeEntry.started_at.desc()).limit(limit)
    result = await db.execute(q)
    entries = list(result.scalars().all())
    return [await _entry_out(db, e) for e in entries]


@router.get("/summary/me", response_model=UserTimeSummary)
async def my_time_summary(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())

    today_secs = await _sum_seconds_for_day(db, current.company_id, current.id, today)
    yesterday_secs = await _sum_seconds_for_day(db, current.company_id, current.id, yesterday)
    week_secs = await _sum_seconds_range(
        db, current.company_id, current.id, week_start, today
    )

    return UserTimeSummary(
        today=TimeSummaryPeriod(label="Today", total_seconds=today_secs, total_label=format_duration(today_secs)),
        yesterday=TimeSummaryPeriod(
            label="Yesterday", total_seconds=yesterday_secs, total_label=format_duration(yesterday_secs)
        ),
        this_week=TimeSummaryPeriod(
            label="This week", total_seconds=week_secs, total_label=format_duration(week_secs)
        ),
    )


@router.get("/summary/project/{project_id}", response_model=ProjectTimeSummary)
async def project_time_summary(
    project_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    project = await db.execute(
        select(Project).where(Project.id == project_id, Project.company_id == current.company_id)
    )
    proj = project.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.duration_seconds), 0)).where(
            TimeEntry.project_id == project_id,
            TimeEntry.company_id == current.company_id,
            TimeEntry.is_running.is_(False),
        )
    )
    total_secs = int(result.scalar_one())
    estimated = float(proj.estimated_hours or 0)
    total_hours = format_hours_decimal(total_secs)
    over = max(0.0, round(total_hours - estimated, 2))

    return ProjectTimeSummary(
        project_id=proj.id,
        project_title=proj.title,
        total_seconds=total_secs,
        total_hours=total_hours,
        total_label=format_duration(total_secs),
        estimated_hours=estimated,
        over_hours=over,
        over_label=f"{over}h" if over else "0h",
    )


def _elapsed_seconds(entry: TimeEntry) -> int:
    end = entry.ended_at or datetime.now(UTC)
    return max(0, int((end - entry.started_at).total_seconds()))


async def _running_entry(db: AsyncSession, company_id: UUID, user_id: UUID) -> TimeEntry | None:
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.company_id == company_id,
            TimeEntry.user_id == user_id,
            TimeEntry.is_running.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _get_task(db: AsyncSession, task_id: UUID, current: CurrentUser) -> Task:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.company_id == current.company_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if current.role_name == "employee" and not current.can("manage_tasks"):
        if task.assigned_to != current.id:
            raise HTTPException(status_code=403, detail="You can only track time on your assigned tasks")
    return task


async def _user_name(db: AsyncSession, user_id: UUID) -> str | None:
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _entry_out(db: AsyncSession, entry: TimeEntry) -> TimeEntryOut:
    task = await db.get(Task, entry.task_id)
    project = await db.get(Project, entry.project_id)
    secs = _elapsed_seconds(entry) if entry.is_running else entry.duration_seconds
    return TimeEntryOut(
        id=entry.id,
        company_id=entry.company_id,
        user_id=entry.user_id,
        user_name=await _user_name(db, entry.user_id),
        project_id=entry.project_id,
        project_title=project.title if project else None,
        task_id=entry.task_id,
        task_title=task.title if task else None,
        started_at=entry.started_at,
        ended_at=entry.ended_at,
        duration_seconds=secs,
        duration_label=format_duration_clock(secs) if entry.is_running else format_duration(secs),
        note=entry.note,
        is_running=entry.is_running,
        created_at=entry.created_at,
    )


async def _sum_seconds_for_day(
    db: AsyncSession, company_id: UUID, user_id: UUID, day: date
) -> int:
    return await _sum_seconds_range(db, company_id, user_id, day, day)


async def _sum_seconds_range(
    db: AsyncSession,
    company_id: UUID,
    user_id: UUID,
    start_day: date,
    end_day: date,
) -> int:
    start_dt = datetime.combine(start_day, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.company_id == company_id,
            TimeEntry.user_id == user_id,
            TimeEntry.started_at >= start_dt,
            TimeEntry.started_at < end_dt,
        )
    )
    total = 0
    for entry in result.scalars().all():
        if entry.is_running:
            total += _elapsed_seconds(entry)
        else:
            total += entry.duration_seconds
    return total
