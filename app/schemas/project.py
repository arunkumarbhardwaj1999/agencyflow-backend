from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    client_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "planning"
    budget: Decimal = Decimal("0")
    start_date: date | None = None
    end_date: date | None = None


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    budget: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    client_id: UUID | None = None


class ProjectOut(ORMModel):
    id: UUID
    company_id: UUID
    client_id: UUID
    title: str
    description: str | None
    status: str
    budget: Decimal
    start_date: date | None
    end_date: date | None
    created_by: UUID | None
    created_at: datetime
    task_total: int = 0
    task_done: int = 0
    progress_percent: int = 0
