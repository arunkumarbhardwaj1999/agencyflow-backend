from decimal import Decimal

from pydantic import BaseModel


class PortalMe(BaseModel):
    client_id: str
    name: str
    business_name: str
    email: str
    company_name: str


class PortalSummary(BaseModel):
    active_projects: int
    completed_projects: int
    total_projects: int
    invoice_count: int
    total_invoiced: Decimal
    total_paid: Decimal
    outstanding: Decimal
