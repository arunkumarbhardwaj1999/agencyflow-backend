from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    business_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = None
    address: str | None = None
    gst_number: str | None = None
    notes: str | None = None
    assigned_user_id: UUID | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    business_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    gst_number: str | None = None
    notes: str | None = None
    assigned_user_id: UUID | None = None


class ClientOut(ORMModel):
    id: UUID
    company_id: UUID
    assigned_user_id: UUID | None
    name: str
    business_name: str
    email: str
    phone: str | None
    address: str | None
    gst_number: str | None
    notes: str | None
    created_at: datetime
    active_projects: int = 0
    invoice_count: int = 0
