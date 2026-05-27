from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class StaffCreateRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=20)
    role: str = Field(pattern=r"^(manager|employee|client)$")


class StaffUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    role: str | None = Field(default=None, pattern=r"^(manager|employee|client)$")
    is_active: bool | None = None


class StaffOut(ORMModel):
    id: UUID
    company_id: UUID | None
    first_name: str
    last_name: str | None
    email: str
    phone: str | None
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
