from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LeadNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class LeadNoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class LeadNoteOut(ORMModel):
    id: UUID
    lead_id: UUID
    content: str
    created_by_id: UUID | None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
