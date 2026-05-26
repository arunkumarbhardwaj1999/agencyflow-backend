from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TaskCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: str = "medium"
    status: str = "todo"
    due_date: datetime | None = None
    assigned_to: UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: datetime | None = None
    assigned_to: UUID | None = None


class TaskOut(ORMModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    assigned_to: UUID | None
    title: str
    description: str | None
    priority: str
    status: str
    due_date: datetime | None
    created_at: datetime
