from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

EXPENSE_CATEGORIES = [
    {"key": "hosting", "label": "Hosting"},
    {"key": "domain", "label": "Domain"},
    {"key": "travel", "label": "Travel"},
    {"key": "software", "label": "Software"},
    {"key": "marketing", "label": "Marketing"},
    {"key": "printing", "label": "Printing"},
    {"key": "miscellaneous", "label": "Others"},
]

VALID_EXPENSE_CATEGORIES = {c["key"] for c in EXPENSE_CATEGORIES}


class ExpenseCreate(BaseModel):
    category: str
    title: str = Field(min_length=1, max_length=255)
    amount: float = Field(ge=0)
    expense_date: date
    notes: str | None = None


class ExpenseUpdate(BaseModel):
    category: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: float | None = Field(default=None, ge=0)
    expense_date: date | None = None
    notes: str | None = None


class ExpenseOut(ORMModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    created_by_id: UUID | None
    created_by_name: str | None = None
    category: str
    category_label: str
    title: str
    amount: float
    expense_date: date
    notes: str | None
    created_at: datetime


class ExpenseCategoryBreakdown(BaseModel):
    category: str
    label: str
    amount: float


class ProjectProfitability(BaseModel):
    project_id: UUID
    project_title: str
    revenue: float
    expenses_total: float
    profit: float
    breakdown: list[ExpenseCategoryBreakdown]
