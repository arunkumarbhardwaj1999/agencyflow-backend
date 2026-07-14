from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InboxItemOut(BaseModel):
    id: str
    channel: str
    channel_label: str
    title: str
    preview: str
    contact_name: str | None = None
    status: str | None = None
    delivery_status: str | None = None
    read_status: str
    created_at: datetime
    is_proxy: bool = False
    sender_name: str | None = None
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    client_id: UUID | None = None
    project_id: UUID | None = None
    invoice_id: UUID | None = None
    link_path: str
    metadata: dict | None = None


class InboxResponse(BaseModel):
    items: list[InboxItemOut]
    total: int
    unread_count: int


class InboxSummary(BaseModel):
    """Rule-based summary — no external AI API required."""

    unread_messages: int
    pending_followups: int
    overdue_invoices: int
    proposals_needing_revision: int
    high_priority_count: int
    summary_lines: list[str]
    note: str = "SMS is used as a WhatsApp proxy until Meta API keys are configured."


class InternalCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    client_id: UUID | None = None
    project_id: UUID | None = None
    invoice_id: UUID | None = None


class InternalCommentOut(BaseModel):
    id: UUID
    body: str
    author_id: UUID | None
    author_name: str | None = None
    lead_id: UUID | None
    deal_id: UUID | None
    client_id: UUID | None
    project_id: UUID | None
    invoice_id: UUID | None
    created_at: datetime


class SendMessagingRequest(BaseModel):
    """Send via SMS (WhatsApp proxy) or log only in mock mode."""

    message: str = Field(min_length=1, max_length=2000)
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    client_id: UUID | None = None
    phone: str | None = None


class MarkReadRequest(BaseModel):
    item_keys: list[str] = Field(min_length=1)
