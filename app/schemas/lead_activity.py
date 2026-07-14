from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

ACTIVITY_TYPES = frozenset({"call", "meeting", "email", "follow_up", "task", "demo", "proposal"})

ACTIVITY_LABELS = {
    "call": "Call",
    "meeting": "Meeting",
    "email": "Email",
    "follow_up": "Follow-up",
    "task": "Task",
    "demo": "Demo",
    "proposal": "Proposal",
}


class LeadActivityCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=30)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    scheduled_at: datetime | None = None
    assigned_to_id: UUID | None = None
    mark_completed: bool = False


class LeadActivityUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    scheduled_at: datetime | None = None
    assigned_to_id: UUID | None = None
    mark_completed: bool | None = None


class LeadActivityOut(ORMModel):
    id: UUID
    lead_id: UUID
    activity_type: str
    activity_label: str
    title: str | None
    notes: str | None
    scheduled_at: datetime | None
    completed_at: datetime | None
    is_completed: bool
    assigned_to_id: UUID | None
    assigned_to_name: str | None = None
    created_by_id: UUID | None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadActivitiesGrouped(BaseModel):
    upcoming: list[LeadActivityOut]
    completed: list[LeadActivityOut]
