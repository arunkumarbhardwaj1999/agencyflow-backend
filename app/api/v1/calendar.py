from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar_service import build_today_agenda, fetch_calendar_events, view_date_range
from app.core.deps import CurrentUser, require_staff
from app.db.session import get_db
from app.schemas.calendar import CalendarEventDetail, CalendarEventsResponse, CalendarTodayAgenda

router = APIRouter(prefix="/calendar", tags=["calendar"])

CALENDAR_VIEWS = {"day", "week", "month"}


@router.get("/events", response_model=CalendarEventsResponse)
async def get_calendar_events(
    view: str = Query("month", description="day | week | month"),
    date_param: date | None = Query(None, alias="date"),
    start: datetime | None = None,
    end: datetime | None = None,
    assigned_to: UUID | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if view not in CALENDAR_VIEWS:
        raise HTTPException(status_code=400, detail=f"Invalid view. Use: {', '.join(CALENDAR_VIEWS)}")

    anchor = date_param or datetime.now(UTC).date()
    if start and end:
        range_start, range_end = start, end
        if range_start.tzinfo is None:
            range_start = range_start.replace(tzinfo=UTC)
        if range_end.tzinfo is None:
            range_end = range_end.replace(tzinfo=UTC)
    else:
        range_start, range_end = view_date_range(view, anchor)

    filter_user = assigned_to
    if current.role_name == "employee" and not current.can("manage_tasks"):
        filter_user = current.id

    events = await fetch_calendar_events(
        db,
        current.company_id,
        range_start,
        range_end,
        assigned_to_id=filter_user,
    )
    return CalendarEventsResponse(
        view=view,
        range_start=range_start,
        range_end=range_end,
        events=events,
        total=len(events),
    )


@router.get("/today", response_model=CalendarTodayAgenda)
async def get_today_agenda(
    assigned_to: UUID | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(UTC).date()
    range_start, range_end = view_date_range("week", today)

    filter_user = assigned_to
    if current.role_name == "employee" and not current.can("manage_tasks"):
        filter_user = current.id

    events = await fetch_calendar_events(
        db,
        current.company_id,
        range_start,
        range_end,
        assigned_to_id=filter_user,
    )
    user_name = f"{current.user.first_name} {current.user.last_name or ''}".strip()
    return build_today_agenda(events, user_name=user_name, today=today)


@router.get("/events/{event_id}", response_model=CalendarEventDetail)
async def get_calendar_event_detail(
    event_id: str,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(UTC).date()
    range_start = datetime(today.year - 1, 1, 1, tzinfo=UTC)
    range_end = datetime(today.year + 1, 12, 31, 23, 59, 59, tzinfo=UTC)

    events = await fetch_calendar_events(
        db,
        current.company_id,
        range_start,
        range_end,
    )
    match = next((e for e in events if e.id == event_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    detail: dict = {"link_path": match.link_path}
    if match.lead_id:
        detail["entity"] = "lead"
        detail["entity_id"] = str(match.lead_id)
    elif match.deal_id:
        detail["entity"] = "deal"
        detail["entity_id"] = str(match.deal_id)
    elif match.project_id:
        detail["entity"] = "project"
        detail["entity_id"] = str(match.project_id)
    elif match.invoice_id:
        detail["entity"] = "invoice"
        detail["entity_id"] = str(match.invoice_id)
    elif match.task_id:
        detail["entity"] = "task"
        detail["entity_id"] = str(match.task_id)

    return CalendarEventDetail(event=match, detail=detail)
