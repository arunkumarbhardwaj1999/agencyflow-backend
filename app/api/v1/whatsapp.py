from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.whatsapp import META_TEMPLATE_NAMES, TEMPLATES, WhatsAppError, normalize_phone, render_template
from app.db.session import get_db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.whatsapp_log import WhatsAppLog
from app.schemas.whatsapp import (
    WhatsAppLogOut,
    WhatsAppSendRequest,
    WhatsAppSendResponse,
    WhatsAppTemplateOut,
)
from app.services.whatsapp_service import deliver_whatsapp, enqueue_whatsapp

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
settings = get_settings()

TEMPLATE_LABELS = {
    "payment_reminder": "Payment reminder",
    "invoice_ready": "Invoice ready",
    "payment_received": "Payment received",
    "task_update": "Task update",
}


def _log_out(row: WhatsAppLog) -> WhatsAppLogOut:
    return WhatsAppLogOut(
        id=row.id,
        client_id=row.client_id,
        phone=row.phone,
        message=row.message,
        status=row.status,
        template_key=row.template_key,
        sent_at=row.sent_at,
    )


@router.get("/templates", response_model=list[WhatsAppTemplateOut])
async def list_templates(current: CurrentUser = Depends(require_staff)):
    return [
        WhatsAppTemplateOut(
            key=key,
            label=TEMPLATE_LABELS.get(key, key.replace("_", " ").title()),
            description=TEMPLATES[key][:120] + "…",
            meta_name=META_TEMPLATE_NAMES.get(key, key),
            requires_approval=settings.whatsapp_enabled,
        )
        for key in TEMPLATES
        if key != "custom"
    ]


@router.get("/logs", response_model=list[WhatsAppLogOut])
async def list_logs(
    limit: int = 20,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WhatsAppLog)
        .where(WhatsAppLog.company_id == current.company_id)
        .order_by(WhatsAppLog.sent_at.desc())
        .limit(min(limit, 50))
    )
    return [_log_out(r) for r in result.scalars().all()]


@router.post("/send", response_model=WhatsAppSendResponse)
async def send_message(
    body: WhatsAppSendRequest,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    client = await db.get(Client, body.client_id)
    if not client or client.company_id != current.company_id:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.phone:
        raise HTTPException(status_code=400, detail="Client has no phone number")

    phone = normalize_phone(client.phone)
    template_key: str | None = None
    params: dict[str, str] = {}

    if body.template == "custom":
        if not body.message:
            raise HTTPException(status_code=400, detail="Message required for custom template")
        text = body.message
    elif body.template == "task_update":
        if not body.project_title or not body.detail:
            raise HTTPException(status_code=400, detail="project_title and detail required")
        template_key = "task_update"
        params = {
            "name": client.business_name,
            "project_title": body.project_title,
            "detail": body.detail,
        }
        text = render_template("task_update", **params)
    else:
        raise HTTPException(
            status_code=400,
            detail="Use /whatsapp/invoices/{id}/notify for invoice templates, or template=custom|task_update",
        )

    queue_status = enqueue_whatsapp(
        company_id=current.company_id,
        client_id=client.id,
        phone=phone,
        message=text,
        template_key=template_key,
        params=params or None,
        use_template=template_key is not None,
    )
    if queue_status == "queued":
        return WhatsAppSendResponse(
            status="queued", phone=phone, message=text, queued=True
        )

    try:
        log = await deliver_whatsapp(
            company_id=current.company_id,
            client_id=client.id,
            phone=phone,
            message=text,
            template_key=template_key,
            params=params or None,
            use_template=template_key is not None,
        )
    except WhatsAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return WhatsAppSendResponse(
        status=log.status, phone=phone, message=text, log_id=log.id, queued=False
    )


@router.post("/invoices/{invoice_id}/notify", response_model=WhatsAppSendResponse)
async def notify_invoice(
    invoice_id: UUID,
    template: str = "payment_reminder",
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    if template not in ("payment_reminder", "invoice_ready", "payment_received"):
        raise HTTPException(
            status_code=400,
            detail="template must be payment_reminder, invoice_ready, or payment_received",
        )

    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.company_id == current.company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = await db.get(Client, invoice.client_id)
    if not client or not client.phone:
        raise HTTPException(status_code=400, detail="Client has no phone number")

    params = {
        "name": client.business_name,
        "invoice_number": invoice.invoice_number,
        "amount": str(invoice.total),
        "due_date": invoice.due_date.isoformat()
        if isinstance(invoice.due_date, date)
        else str(invoice.due_date),
    }
    text = render_template(template, **params)
    phone = normalize_phone(client.phone)

    queue_status = enqueue_whatsapp(
        company_id=current.company_id,
        client_id=client.id,
        phone=phone,
        message=text,
        template_key=template,
        params=params,
    )
    if queue_status == "queued":
        return WhatsAppSendResponse(
            status="queued", phone=phone, message=text, queued=True
        )

    try:
        log = await deliver_whatsapp(
            company_id=current.company_id,
            client_id=client.id,
            phone=phone,
            message=text,
            template_key=template,
            params=params,
        )
    except WhatsAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return WhatsAppSendResponse(
        status=log.status, phone=phone, message=text, log_id=log.id, queued=False
    )
