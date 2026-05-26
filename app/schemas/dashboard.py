from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    open_leads: int
    active_projects: int
    paid_invoices: int
    unpaid_invoice_total: Decimal
    pipeline_value: Decimal


class UpcomingDeadline(BaseModel):
    id: UUID
    type: str
    title: str
    due_at: datetime


class ActivityEvent(BaseModel):
    id: str
    type: str
    message: str
    created_at: datetime


class DashboardResponse(BaseModel):
    kpis: DashboardKPIs
    upcoming_deadlines: list[UpcomingDeadline]
    recent_activity: list[ActivityEvent]
