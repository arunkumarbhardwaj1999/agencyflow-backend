from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
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
