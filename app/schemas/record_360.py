from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.communication import InboxItemOut
from app.schemas.deal import DealOut
from app.schemas.document import ClientDocumentOut, DealAttachmentOut, LeadAttachmentOut
from app.schemas.lead import LeadOut
from app.schemas.deal_activity import DealActivitiesGrouped
from app.schemas.lead_activity import LeadActivitiesGrouped
from app.schemas.deal_timeline import DealTimelineOut
from app.schemas.lead_timeline import LeadTimelineOut


class RelatedDealBrief(BaseModel):
    id: UUID
    title: str
    status: str
    value: float
    expected_close_date: date | None = None


class RelatedLeadBrief(BaseModel):
    id: UUID
    name: str
    status: str
    company_name: str | None = None


class RelatedClientBrief(BaseModel):
    id: UUID
    name: str
    business_name: str
    email: str


class RelatedProjectBrief(BaseModel):
    id: UUID
    title: str
    status: str
    end_date: date | None = None
    progress_percent: int = 0


class RelatedInvoiceBrief(BaseModel):
    id: UUID
    invoice_number: str
    status: str
    total: float
    due_date: date


class Record360Related(BaseModel):
    leads: list[RelatedLeadBrief] = []
    deals: list[RelatedDealBrief] = []
    clients: list[RelatedClientBrief] = []
    projects: list[RelatedProjectBrief] = []
    invoices: list[RelatedInvoiceBrief] = []


class Record360Insights(BaseModel):
    score: int | None = None
    confidence: str | None = None
    summary: str
    recommendations: list[str] = []


class Record360View(BaseModel):
    entity_type: str
    entity_id: UUID
    entity: LeadOut | DealOut | dict
    timeline: list[LeadTimelineOut | DealTimelineOut]
    activities: LeadActivitiesGrouped | DealActivitiesGrouped | None = None
    notes: list
    attachments: list[LeadAttachmentOut | DealAttachmentOut | ClientDocumentOut]
    emails: list
    messaging: list[InboxItemOut]
    tasks: list
    meetings: list
    internal_comments: list
    related: Record360Related
    insights: Record360Insights
