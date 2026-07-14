from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

DEAL_ACTIVITY_TYPES = frozenset({"call", "meeting", "email", "follow_up", "task", "demo", "proposal"})

DEAL_ACTIVITY_LABELS = {
    "call": "Call",
    "meeting": "Meeting",
    "email": "Email",
    "follow_up": "Follow-up",
    "task": "Task",
    "demo": "Demo",
    "proposal": "Proposal",
}


class DealNoteCreate(BaseModel):
    content: str = Field(min_length=1)


class DealNoteUpdate(BaseModel):
    content: str = Field(min_length=1)


class DealNoteOut(ORMModel):
    id: UUID
    deal_id: UUID
    content: str
    created_by_id: UUID | None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class DealActivityCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=30)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    scheduled_at: datetime | None = None
    assigned_to_id: UUID | None = None
    mark_completed: bool = False


class DealActivityUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    scheduled_at: datetime | None = None
    assigned_to_id: UUID | None = None
    mark_completed: bool | None = None


class DealActivityOut(ORMModel):
    id: UUID
    deal_id: UUID
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


class DealActivitiesGrouped(BaseModel):
    upcoming: list[DealActivityOut]
    completed: list[DealActivityOut]


class DealEmailOut(ORMModel):
    id: UUID
    deal_id: UUID
    subject: str
    body: str
    from_email: str
    to_email: str
    delivery_status: str
    open_status: str
    opened_at: datetime | None
    sent_by_id: UUID | None
    sent_by_name: str | None = None
    error_message: str | None
    sent_at: datetime


class DealAttachmentRename(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
