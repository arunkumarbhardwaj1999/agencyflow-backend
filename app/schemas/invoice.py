from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class InvoiceItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(ge=0)


class InvoiceItemOut(ORMModel):
    id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class InvoiceCreate(BaseModel):
    client_id: UUID
    due_date: date
    items: list[InvoiceItemIn] = Field(min_length=1)
    tax_rate: Decimal = Field(default=Decimal("0.18"), ge=0, le=1)
    place_of_supply: str | None = Field(default=None, max_length=2)
    status: str = "unpaid"
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    due_date: date | None = None
    status: str | None = None
    notes: str | None = None
    payment_link: str | None = None


class InvoiceOut(ORMModel):
    id: UUID
    company_id: UUID
    client_id: UUID
    client_name: str | None = None
    invoice_number: str
    subtotal: Decimal
    tax: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    tax_type: str
    place_of_supply: str | None
    total: Decimal
    status: str
    due_date: date
    notes: str | None = None
    payment_link: str | None
    payment_provider: str | None = None
    paid_at: datetime | None = None
    items: list[InvoiceItemOut] = []
    created_at: datetime
