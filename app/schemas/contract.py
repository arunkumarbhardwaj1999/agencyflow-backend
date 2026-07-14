from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

CONTRACT_STATUSES = {"draft", "sent", "signed", "active", "expired"}


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    client_id: UUID
    proposal_id: UUID | None = None
    project_value: float = 0
    services: list[str] = Field(default_factory=list)
    body: str | None = None
    expires_at: date | None = None
    auto_renewal_reminder: bool = True
    renewal_reminder_days: int = 30


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = None
    project_value: float | None = None
    services: list[str] | None = None
    expires_at: date | None = None
    auto_renewal_reminder: bool | None = None
    renewal_reminder_days: int | None = None
    status: str | None = None


class ContractSignRequest(BaseModel):
    signer_name: str = Field(min_length=1, max_length=255)
    signer_email: str = Field(min_length=1, max_length=255)
    accept_terms: bool = True


class ContractOut(ORMModel):
    id: UUID
    company_id: UUID
    proposal_id: UUID | None
    client_id: UUID
    client_name: str | None = None
    created_by_id: UUID | None
    created_by_name: str | None = None
    renewed_from_id: UUID | None
    contract_number: str
    title: str
    project_value: float
    services: list[str]
    body: str | None
    status: str
    signer_name: str | None
    signer_email: str | None
    signed_at: datetime | None
    sent_at: datetime | None
    starts_at: date | None
    expires_at: date | None
    auto_renewal_reminder: bool
    renewal_reminder_days: int
    days_until_expiry: int | None = None
    renewal_due_soon: bool = False
    created_at: datetime
    updated_at: datetime


class ContractExpiryReminder(BaseModel):
    contract_id: UUID
    contract_number: str
    title: str
    client_name: str
    expires_at: date
    days_remaining: int
