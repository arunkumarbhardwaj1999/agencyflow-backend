from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    source: str | None = None
    status: str = "new"
    value: Decimal = Decimal("0")
    notes: str | None = None
    next_followup: datetime | None = None
    assigned_user_id: UUID | None = None


class LeadUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    source: str | None = None
    status: str | None = None
    value: Decimal | None = None
    notes: str | None = None
    next_followup: datetime | None = None
    assigned_user_id: UUID | None = None


class LeadOut(ORMModel):
    id: UUID
    company_id: UUID
    assigned_user_id: UUID | None
    name: str
    email: str | None
    phone: str | None
    company_name: str | None
    source: str | None
    status: str
    value: Decimal
    notes: str | None
    next_followup: datetime | None
    created_at: datetime
