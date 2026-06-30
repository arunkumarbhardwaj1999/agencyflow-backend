from pydantic import BaseModel


class PaymentLinkRequest(BaseModel):
    provider: str = "razorpay"  # "razorpay" | "stripe"


class PaymentLinkResponse(BaseModel):
    provider: str
    url: str
    order_id: str


class WebhookAck(BaseModel):
    received: bool = True
    invoice_status: str | None = None
