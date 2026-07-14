from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DealTimelineOut(ORMModel):
    id: UUID
    deal_id: UUID
    event_type: str
    description: str
    created_by_id: UUID | None
    created_by_name: str | None = None
    metadata: dict | None = None
    created_at: datetime


class DealSendEmailRequest(BaseModel):
    content: str = Field(min_length=1)
    subject: str | None = None
