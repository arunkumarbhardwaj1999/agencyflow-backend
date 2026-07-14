from pydantic import BaseModel, Field


class EmailIntegrationStatus(BaseModel):
    enabled: bool
    provider: str
    from_address: str | None = None


class WhatsAppIntegrationStatus(BaseModel):
    enabled: bool
    provider: str
    token_configured: bool
    phone_number_id_configured: bool
    business_account_id: str | None = None
    celery_queue: bool
    auto_on_payment: bool
    auto_on_invoice_send: bool
    webhook_path: str = "/api/v1/whatsapp/webhook"


class IntegrationsStatus(BaseModel):
    email: EmailIntegrationStatus
    whatsapp: WhatsAppIntegrationStatus
    meta_business_hint: str = "Agency-flow"


class WhatsAppTestRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20, description="Indian mobile, e.g. 9876543210")


class WhatsAppTestResponse(BaseModel):
    status: str
    phone: str
    message_id: str | None = None
    delivery: str
    detail: str | None = None
