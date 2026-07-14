from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

DEAL_STAGES = ("qualification", "proposal_sent", "negotiation", "won", "lost")

DEAL_STAGE_LABELS = {
    "qualification": "Qualification",
    "proposal_sent": "Proposal Sent",
    "negotiation": "Negotiation",
    "won": "Won",
    "lost": "Lost",
}

STAGE_DEFAULT_PROBABILITY = {
    "qualification": 25,
    "proposal_sent": 50,
    "negotiation": 75,
    "won": 100,
    "lost": 0,
}


class DealCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    lead_id: UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company_name: str | None = None
    value: Decimal = Decimal("0")
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    status: str = "qualification"
    source: str | None = None
    notes: str | None = None
    assigned_user_id: UUID | None = None


class DealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company_name: str | None = None
    value: Decimal | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    status: str | None = None
    source: str | None = None
    notes: str | None = None
    lost_reason: str | None = None
    assigned_user_id: UUID | None = None


class DealKanbanMove(BaseModel):
    status: str
    kanban_position: int = Field(ge=0, default=0)


class DealOut(ORMModel):
    id: UUID
    company_id: UUID
    lead_id: UUID | None
    client_id: UUID | None
    assigned_user_id: UUID | None
    assigned_to_name: str | None = None
    title: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    company_name: str | None
    value: Decimal
    probability: int
    expected_close_date: date | None
    status: str
    status_label: str | None = None
    kanban_position: int
    source: str | None
    notes: str | None
    lost_reason: str | None
    created_at: datetime
    updated_at: datetime


class DealKanbanColumn(BaseModel):
    stage: str
    label: str
    deals: list[DealOut]


class DealKanbanBoard(BaseModel):
    columns: list[DealKanbanColumn]
    total_pipeline_value: Decimal
    open_deal_count: int


class DealInsights(BaseModel):
    probability: int
    confidence: str
    summary: str
    recommendations: list[str]


class CreateDealFromLeadRequest(BaseModel):
    title: str | None = None
    value: Decimal | None = None
    expected_close_date: date | None = None
    assigned_user_id: UUID | None = None
