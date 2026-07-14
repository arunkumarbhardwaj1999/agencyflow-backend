from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TimeEntryOut(ORMModel):
    id: UUID
    company_id: UUID
    user_id: UUID
    user_name: str | None = None
    project_id: UUID
    project_title: str | None = None
    task_id: UUID
    task_title: str | None = None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    duration_label: str
    note: str | None
    is_running: bool
    created_at: datetime


class TimerStartRequest(BaseModel):
    task_id: UUID


class ActiveTimerOut(BaseModel):
    running: bool
    entry: TimeEntryOut | None = None
    elapsed_seconds: int = 0


class TimeSummaryPeriod(BaseModel):
    label: str
    total_seconds: int
    total_label: str


class UserTimeSummary(BaseModel):
    today: TimeSummaryPeriod
    yesterday: TimeSummaryPeriod
    this_week: TimeSummaryPeriod


class ProjectTimeSummary(BaseModel):
    project_id: UUID
    project_title: str
    total_seconds: int
    total_hours: float
    total_label: str
    estimated_hours: float
    over_hours: float
    over_label: str
