"""WhatsApp delivery + persistence. Queues via Celery when Redis is available."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.whatsapp import WhatsAppError, normalize_phone, render_template, send_message
from app.db.session import AsyncSessionLocal
from app.models.whatsapp_log import WhatsAppLog

logger = logging.getLogger("agencyflow.whatsapp")
settings = get_settings()


async def persist_log(
    db: AsyncSession,
    *,
    company_id: UUID,
    client_id: UUID | None,
    phone: str,
    message: str,
    status: str,
    template_key: str | None = None,
) -> WhatsAppLog:
    row = WhatsAppLog(
        company_id=company_id,
        client_id=client_id,
        phone=phone,
        message=message,
        status=status,
        template_key=template_key,
    )
    db.add(row)
    await db.flush()
    return row


async def deliver_whatsapp(
    *,
    company_id: UUID,
    client_id: UUID | None,
    phone: str,
    message: str,
    template_key: str | None = None,
    params: dict[str, str] | None = None,
    use_template: bool = True,
) -> WhatsAppLog:
    """Send a WhatsApp message and persist the log."""
    normalized = normalize_phone(phone)
    try:
        result = await send_message(
            phone=normalized,
            template_key=template_key,
            params=params,
            text=message if not template_key else None,
            use_template=use_template,
        )
        status = result.get("status", "sent")
    except WhatsAppError as exc:
        logger.warning("WhatsApp delivery failed: %s", exc)
        status = "failed"
        result = {"status": "failed", "to": normalized}

    async with AsyncSessionLocal() as db:
        log = await persist_log(
            db,
            company_id=company_id,
            client_id=client_id,
            phone=result.get("to", normalized),
            message=message,
            status=status,
            template_key=template_key,
        )
        await db.commit()
        await db.refresh(log)
        return log


def enqueue_whatsapp(
    *,
    company_id: UUID,
    client_id: UUID | None,
    phone: str,
    message: str,
    template_key: str | None = None,
    params: dict[str, str] | None = None,
    use_template: bool = True,
) -> str:
    """Queue WhatsApp delivery via Celery, or run in-process if Redis is unavailable."""
    payload = {
        "company_id": str(company_id),
        "client_id": str(client_id) if client_id else None,
        "phone": phone,
        "message": message,
        "template_key": template_key,
        "params": params or {},
        "use_template": use_template,
    }
    try:
        from app.tasks.whatsapp_tasks import send_whatsapp_task

        send_whatsapp_task.delay(**payload)
        return "queued"
    except Exception as exc:
        logger.info("Celery unavailable (%s), sending WhatsApp in-process", exc)
        asyncio.create_task(
            deliver_whatsapp(
                company_id=company_id,
                client_id=client_id,
                phone=phone,
                message=message,
                template_key=template_key,
                params=params,
                use_template=use_template,
            )
        )
        return "processing"


async def notify_invoice_payment_received(
    db: AsyncSession,
    *,
    company_id: UUID,
    client_id: UUID,
    client_name: str,
    client_phone: str,
    invoice_number: str,
    amount: str,
) -> None:
    if not settings.whatsapp_auto_on_payment:
        return
    message = render_template(
        "payment_received",
        name=client_name,
        invoice_number=invoice_number,
        amount=amount,
    )
    params = {"name": client_name, "invoice_number": invoice_number, "amount": amount}
    enqueue_whatsapp(
        company_id=company_id,
        client_id=client_id,
        phone=client_phone,
        message=message,
        template_key="payment_received",
        params=params,
    )


async def notify_invoice_ready(
    db: AsyncSession,
    *,
    company_id: UUID,
    client_id: UUID,
    client_name: str,
    client_phone: str,
    invoice_number: str,
    amount: str,
) -> None:
    if not settings.whatsapp_auto_on_invoice_send:
        return
    message = render_template(
        "invoice_ready",
        name=client_name,
        invoice_number=invoice_number,
        amount=amount,
    )
    params = {"name": client_name, "invoice_number": invoice_number, "amount": amount}
    enqueue_whatsapp(
        company_id=company_id,
        client_id=client_id,
        phone=client_phone,
        message=message,
        template_key="invoice_ready",
        params=params,
    )
