from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LeadEmailOut(ORMModel):
    id: UUID
    lead_id: UUID
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


class DuplicateLeadMatch(BaseModel):
    lead_id: UUID
    name: str
    email: str | None
    phone: str | None
    company_name: str | None
    status: str
    created_at: datetime
    match_fields: list[str]


class LeadDuplicateCheckResponse(BaseModel):
    has_duplicates: bool
    duplicates: list[DuplicateLeadMatch]


class LeadMergeRequest(BaseModel):
    source_lead_id: UUID = Field(description="Lead to merge into the target (will be deleted)")


class LeadAttachmentRename(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
