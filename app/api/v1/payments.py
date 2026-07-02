"""Payment links + provider webhooks.

- POST /payments/invoices/{id}/link        -> create a hosted payment link
- POST /payments/webhook/razorpay          -> Razorpay webhook (marks invoice paid)
- POST /payments/webhook/stripe            -> Stripe webhook (marks invoice paid)
- POST /payments/invoices/{id}/simulate    -> dev-only: mark paid without a gateway

Webhooks are public (no auth) but verify the provider signature. They look the
invoice up by the stored provider order id.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission
from app.core import payments as pay
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.client import Client
from app.models.invoice import Invoice
from app.schemas.payment import PaymentLinkRequest, PaymentLinkResponse, WebhookAck
from app.services.whatsapp_service import notify_invoice_payment_received

router = APIRouter(prefix="/payments", tags=["payments"])
settings = get_settings()


async def _mark_paid(db: AsyncSession, invoice: Invoice, payment_id: str | None) -> None:
    invoice.status = "paid"
    invoice.paid_at = datetime.now(UTC)
    if payment_id:
        invoice.provider_payment_id = payment_id
    await db.flush()
    await realtime_manager.broadcast(
        invoice.company_id, "invoice", f"Invoice {invoice.invoice_number} paid"
    )
    client = await db.get(Client, invoice.client_id)
    if client and client.phone:
        await notify_invoice_payment_received(
            db,
            company_id=invoice.company_id,
            client_id=client.id,
            client_name=client.business_name,
            client_phone=client.phone,
            invoice_number=invoice.invoice_number,
            amount=str(invoice.total),
        )


async def _invoice_by_order(db: AsyncSession, order_id: str | None) -> Invoice | None:
    if not order_id:
        return None
    result = await db.execute(select(Invoice).where(Invoice.provider_order_id == order_id))
    return result.scalar_one_or_none()


@router.post("/invoices/{invoice_id}/link", response_model=PaymentLinkResponse)
async def create_link(
    invoice_id: UUID,
    body: PaymentLinkRequest,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.company_id == current.company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Invoice is already paid")

    client = await db.get(Client, invoice.client_id)
    try:
        link = pay.create_payment_link(
            provider=body.provider,
            invoice_id=str(invoice.id),
            invoice_number=invoice.invoice_number,
            amount=invoice.total,
            currency=settings.currency,
            customer_name=client.business_name if client else "Customer",
            customer_email=client.email if client else None,
        )
    except pay.PaymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    invoice.payment_provider = link.provider
    invoice.provider_order_id = link.order_id
    invoice.payment_link = link.url
    await db.flush()
    return PaymentLinkResponse(provider=link.provider, url=link.url, order_id=link.order_id)


@router.post("/webhook/razorpay", response_model=WebhookAck)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    if not pay.verify_razorpay_signature(raw, x_razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    event = pay.parse_razorpay_event(raw)
    if not event["paid"]:
        return WebhookAck(received=True)

    invoice = await _invoice_by_order(db, event["order_id"])
    if invoice and invoice.status != "paid":
        await _mark_paid(db, invoice, event["payment_id"])
        return WebhookAck(received=True, invoice_status="paid")
    return WebhookAck(received=True)


@router.post("/webhook/stripe", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    try:
        event = pay.verify_stripe_event(raw, stripe_signature)
    except pay.PaymentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not event["paid"]:
        return WebhookAck(received=True)

    invoice = await _invoice_by_order(db, event["order_id"])
    if invoice and invoice.status != "paid":
        await _mark_paid(db, invoice, event["payment_id"])
        return WebhookAck(received=True, invoice_status="paid")
    return WebhookAck(received=True)


@router.post("/invoices/{invoice_id}/simulate", response_model=WebhookAck)
async def simulate_payment(
    invoice_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    """Dev helper: mark an invoice paid as if a gateway webhook fired.
    Only available while PAYMENTS_MOCK is enabled."""
    if not settings.payments_mock:
        raise HTTPException(status_code=403, detail="Simulation disabled in production")
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.company_id == current.company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "paid":
        await _mark_paid(db, invoice, f"mock_pay_{invoice_id}")
    return WebhookAck(received=True, invoice_status="paid")
