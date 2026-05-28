from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_company, require_permission
from app.core.realtime import realtime_manager
from app.db.session import get_db
from app.models.client import Client
from app.models.invoice import Invoice
from app.schemas.common import MessageResponse
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceUpdate

router = APIRouter(prefix="/invoices", tags=["invoices"])

INVOICE_STATUSES = {"unpaid", "paid", "overdue", "cancelled"}


def _calc_tax_total(subtotal: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    tax = (subtotal * tax_rate).quantize(Decimal("0.01"))
    total = (subtotal + tax).quantize(Decimal("0.01"))
    return tax, total


async def _next_invoice_number(db: AsyncSession, company_id: UUID) -> str:
    count = await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.company_id == company_id)
    )
    seq = count.scalar_one() + 1
    return f"INV-{datetime.now(UTC).year}-{seq:04d}"


async def _get_invoice(db: AsyncSession, invoice_id: UUID, company_id: UUID) -> Invoice:
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.company_id == company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


async def _enrich(db: AsyncSession, invoice: Invoice) -> InvoiceOut:
    client_name: str | None = None
    if invoice.client_id:
        client_result = await db.execute(select(Client.business_name).where(Client.id == invoice.client_id))
        client_name = client_result.scalar_one_or_none()
    return InvoiceOut(
        id=invoice.id,
        company_id=invoice.company_id,
        client_id=invoice.client_id,
        client_name=client_name,
        invoice_number=invoice.invoice_number,
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        total=invoice.total,
        status=invoice.status,
        due_date=invoice.due_date,
        payment_link=invoice.payment_link,
        created_at=invoice.created_at,
    )


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    status: str | None = None,
    client_id: UUID | None = None,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    q = select(Invoice).where(Invoice.company_id == current.company_id).order_by(Invoice.created_at.desc())
    if status:
        q = q.where(Invoice.status == status)
    if client_id:
        q = q.where(Invoice.client_id == client_id)
    result = await db.execute(q)
    invoices = result.scalars().all()
    return [await _enrich(db, inv) for inv in invoices]


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    current: CurrentUser = Depends(require_permission("manage_invoices")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in INVOICE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use: {', '.join(INVOICE_STATUSES)}")
    client = await db.execute(
        select(Client).where(Client.id == body.client_id, Client.company_id == current.company_id)
    )
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    tax, total = _calc_tax_total(body.subtotal, body.tax_rate)
    invoice = Invoice(
        company_id=current.company_id,
        client_id=body.client_id,
        invoice_number=await _next_invoice_number(db, current.company_id),
        subtotal=body.subtotal,
        tax=tax,
        total=total,
        status=body.status,
        due_date=body.due_date,
        payment_link=body.payment_link,
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)
    await realtime_manager.broadcast(
        current.company_id, "invoice", f"Invoice {invoice.invoice_number} created"
    )
    return await _enrich(db, invoice)


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

    tax_rate = data.pop("tax_rate", None)
    subtotal = data.pop("subtotal", None) or invoice.subtotal
    if subtotal != invoice.subtotal or tax_rate is not None:
        rate = tax_rate if tax_rate is not None else (
            (Decimal(invoice.tax) / Decimal(invoice.subtotal)) if invoice.subtotal else Decimal("0.18")
        )
        tax, total = _calc_tax_total(Decimal(subtotal), Decimal(rate))
        invoice.subtotal = subtotal
        invoice.tax = tax
        invoice.total = total

    for key, value in data.items():
        setattr(invoice, key, value)

    await db.flush()
    await db.refresh(invoice)
    await realtime_manager.broadcast(
        current.company_id, "invoice", f"Invoice {invoice.invoice_number} updated"
    )
    return await _enrich(db, invoice)


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
