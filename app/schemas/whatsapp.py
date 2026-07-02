from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class WhatsAppSendRequest(BaseModel):
    client_id: UUID
    template: str = Field(
        description="payment_reminder | invoice_ready | payment_received | task_update | custom"
    )
    message: str | None = Field(default=None, max_length=4096)
    project_title: str | None = None
    detail: str | None = None


class WhatsAppLogOut(ORMModel):
    id: UUID
    client_id: UUID | None
    phone: str
    message: str
    status: str
    template_key: str | None = None
    sent_at: datetime


class WhatsAppSendResponse(BaseModel):
    status: str
    phone: str
    message: str
    log_id: UUID | None = None
    queued: bool = False


class WhatsAppTemplateOut(BaseModel):
    key: str
    label: str
    description: str
    meta_name: str
    requires_approval: bool = True
