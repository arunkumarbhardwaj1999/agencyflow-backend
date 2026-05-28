from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class InvoiceCreate(BaseModel):
    client_id: UUID
    subtotal: Decimal = Field(gt=0, decimal_places=2)
    due_date: date
    tax_rate: Decimal = Field(default=Decimal("0.18"), ge=0, le=1)
    status: str = "unpaid"
    payment_link: str | None = None


class InvoiceUpdate(BaseModel):
    subtotal: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    due_date: date | None = None
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    status: str | None = None
    payment_link: str | None = None


class InvoiceOut(ORMModel):
    id: UUID
    company_id: UUID
    client_id: UUID
    client_name: str | None = None
    invoice_number: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: str
    due_date: date
    payment_link: str | None
    created_at: datetime
