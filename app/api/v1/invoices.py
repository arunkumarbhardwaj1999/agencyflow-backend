from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.automation_engine import fire_trigger
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission
from app.core.email import send_invoice_email
from app.core.gst import (
    compute_gst,
    resolve_place_of_supply,
    state_code_from_gstin,
)
from app.core.pdf import PdfInvoice, PdfItem, build_invoice_pdf
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.schemas.common import MessageResponse
from app.schemas.invoice import InvoiceCreate, InvoiceItemOut, InvoiceOut, InvoiceUpdate
from app.services.whatsapp_service import notify_invoice_ready

router = APIRouter(prefix="/invoices", tags=["invoices"])

INVOICE_STATUSES = {"unpaid", "paid", "overdue", "cancelled"}
TWO_PLACES = Decimal("0.01")
settings = get_settings()


async def _next_invoice_number(db: AsyncSession, company_id: UUID) -> str:
    count = await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.company_id == company_id)
    )
    seq = count.scalar_one() + 1
    return f"INV-{datetime.now(UTC).year}-{seq:04d}"


async def _get_invoice(db: AsyncSession, invoice_id: UUID, company_id: UUID) -> Invoice:
    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id, Invoice.company_id == company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


async def _client_name(db: AsyncSession, client_id: UUID | None) -> str | None:
    if not client_id:
        return None
    result = await db.execute(select(Client.business_name).where(Client.id == client_id))
    return result.scalar_one_or_none()


def _to_out(invoice: Invoice, client_name: str | None) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id,
        company_id=invoice.company_id,
        client_id=invoice.client_id,
        client_name=client_name,
        invoice_number=invoice.invoice_number,
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        cgst=invoice.cgst,
        sgst=invoice.sgst,
        igst=invoice.igst,
        tax_type=invoice.tax_type,
        place_of_supply=invoice.place_of_supply,
        total=invoice.total,
        status=invoice.status,
        due_date=invoice.due_date,
        notes=invoice.notes,
        payment_link=invoice.payment_link,
        payment_provider=invoice.payment_provider,
        paid_at=invoice.paid_at,
        items=[
            InvoiceItemOut(
                id=it.id,
                description=it.description,
                quantity=it.quantity,
                unit_price=it.unit_price,
                amount=it.amount,
            )
            for it in invoice.items
        ],
        created_at=invoice.created_at,
    )


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    status: str | None = None,
    client_id: UUID | None = None,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.company_id == current.company_id)
        .order_by(Invoice.created_at.desc())
    )
    if status:
        q = q.where(Invoice.status == status)
    if client_id:
        q = q.where(Invoice.client_id == client_id)
    result = await db.execute(q)
    invoices = result.scalars().all()
    return [_to_out(inv, await _client_name(db, inv.client_id)) for inv in invoices]


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in INVOICE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use: {', '.join(INVOICE_STATUSES)}")

    client_result = await db.execute(
        select(Client).where(Client.id == body.client_id, Client.company_id == current.company_id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    company = await db.get(Company, current.company_id)
    supplier_state = (company.state_code if company else None) or state_code_from_gstin(
        company.gst_number if company else None
    )
    client_state = client.state_code or state_code_from_gstin(client.gst_number)
    place_of_supply = resolve_place_of_supply(body.place_of_supply, client.gst_number, supplier_state)
    if not place_of_supply:
        place_of_supply = client_state

    # Build line items and subtotal
    items: list[InvoiceItem] = []
    subtotal = Decimal("0.00")
    for line in body.items:
        amount = (Decimal(line.quantity) * Decimal(line.unit_price)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        subtotal += amount
        items.append(
            InvoiceItem(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=amount,
            )
        )
    subtotal = subtotal.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    gst = compute_gst(subtotal, body.tax_rate, supplier_state, place_of_supply)

    invoice = Invoice(
        company_id=current.company_id,
        client_id=body.client_id,
        invoice_number=await _next_invoice_number(db, current.company_id),
        subtotal=gst.subtotal,
        tax=gst.tax_total,
        cgst=gst.cgst,
        sgst=gst.sgst,
        igst=gst.igst,
        tax_type=gst.tax_type,
        place_of_supply=gst.place_of_supply,
        total=gst.total,
        status=body.status,
        due_date=body.due_date,
        notes=body.notes,
        items=items,
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice, attribute_names=["items"])
    await realtime_manager.broadcast(
        current.company_id, "invoice", f"Invoice {invoice.invoice_number} created"
    )
    return _to_out(invoice, client.business_name)


@router.patch("/{invoice_id}", response_model=InvoiceOut)
async def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    invoice = await _get_invoice(db, invoice_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in INVOICE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    if data.get("status") == "paid" and invoice.paid_at is None:
        invoice.paid_at = datetime.now(UTC)

    for key, value in data.items():
        setattr(invoice, key, value)

    await db.flush()
    await db.refresh(invoice, attribute_names=["items"])
    if data.get("status") == "paid":
        await fire_trigger(
            db,
            company_id=current.company_id,
            trigger_key="invoice_paid",
            entity_type="invoice",
            entity_id=invoice.id,
            context={"invoice_number": invoice.invoice_number},
        )
    await realtime_manager.broadcast(
        current.company_id, "invoice", f"Invoice {invoice.invoice_number} updated"
    )
    return _to_out(invoice, await _client_name(db, invoice.client_id))


async def render_invoice_pdf(db: AsyncSession, invoice: Invoice) -> bytes:
    """Build the PDF bytes for an invoice (items must already be loaded)."""
    company = await db.get(Company, invoice.company_id)
    client = await db.get(Client, invoice.client_id)
    return build_invoice_pdf(
        PdfInvoice(
            invoice_number=invoice.invoice_number,
            created_on=invoice.created_at.date(),
            due_date=invoice.due_date,
            status=invoice.status,
            company_name=company.company_name if company else "Agency",
            company_email=company.email if company else None,
            company_gstin=company.gst_number if company else None,
            company_address=company.address if company else None,
            client_name=client.business_name if client else "Client",
            client_email=client.email if client else None,
            client_gstin=client.gst_number if client else None,
            client_address=client.address if client else None,
            place_of_supply=invoice.place_of_supply,
            items=[
                PdfItem(
                    description=it.description,
                    quantity=Decimal(it.quantity),
                    unit_price=Decimal(it.unit_price),
                    amount=Decimal(it.amount),
                )
                for it in invoice.items
            ],
            subtotal=Decimal(invoice.subtotal),
            cgst=Decimal(invoice.cgst),
            sgst=Decimal(invoice.sgst),
            igst=Decimal(invoice.igst),
            tax_type=invoice.tax_type,
            total=Decimal(invoice.total),
            currency=settings.currency,
            notes=invoice.notes,
        )
    )


def pdf_response(invoice_number: str, pdf_bytes: bytes) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice_number}.pdf"'},
    )


@router.get("/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    invoice = await _get_invoice(db, invoice_id, current.company_id)
    pdf_bytes = await render_invoice_pdf(db, invoice)
    return pdf_response(invoice.invoice_number, pdf_bytes)


@router.post("/{invoice_id}/send", response_model=MessageResponse)
async def send_invoice(
    invoice_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    invoice = await _get_invoice(db, invoice_id, current.company_id)
    client = await db.get(Client, invoice.client_id)
    if not client or not client.email:
        raise HTTPException(status_code=400, detail="Client has no email address")

    company = await db.get(Company, current.company_id)
    pdf_bytes = await render_invoice_pdf(db, invoice)
    sent = await send_invoice_email(
        to=client.email,
        invoice_number=invoice.invoice_number,
        company_name=company.company_name if company else "AgencyFlow",
        pdf_bytes=pdf_bytes,
        pay_link=invoice.payment_link,
    )
    if not sent:
        raise HTTPException(status_code=502, detail="Could not send the invoice email")

    if client.phone:
        await notify_invoice_ready(
            db,
            company_id=current.company_id,
            client_id=client.id,
            client_name=client.business_name,
            client_phone=client.phone,
            invoice_number=invoice.invoice_number,
            amount=str(invoice.total),
        )

    mode = "sent" if settings.email_enabled else "logged (mock mode — set RESEND_API_KEY to send)"
    return MessageResponse(message=f"Invoice {invoice.invoice_number} emailed to {client.email} ({mode})")


@router.delete("/{invoice_id}", response_model=MessageResponse)
async def delete_invoice(
    invoice_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    invoice = await _get_invoice(db, invoice_id, current.company_id)
    number = invoice.invoice_number
    await db.delete(invoice)
    await realtime_manager.broadcast(current.company_id, "invoice", f"Invoice {number} removed")
    return MessageResponse(message="Invoice deleted")
