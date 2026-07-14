from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CalendarEventOut(BaseModel):
    id: str
    title: str
    event_type: str
    color: str
    icon: str
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    source_type: str
    source_id: UUID
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    project_id: UUID | None = None
    invoice_id: UUID | None = None
    task_id: UUID | None = None
    assigned_to_id: UUID | None = None
    assigned_to_name: str | None = None
    description: str | None = None
    status: str | None = None
    link_path: str
    priority: int = 0


class CalendarEventsResponse(BaseModel):
    view: str
    range_start: datetime
    range_end: datetime
    events: list[CalendarEventOut]
    total: int


class CalendarAgendaItem(BaseModel):
    event: CalendarEventOut
    reason: str


class CalendarTodayAgenda(BaseModel):
    greeting: str
    user_name: str
    date: date
    priorities: list[CalendarAgendaItem]
    events_today: list[CalendarEventOut]
    summary: str


class CalendarEventDetail(BaseModel):
    event: CalendarEventOut
    detail: dict | None = None
