from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


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
    avg_progress_percent: int
    pending_approvals: int
    invoice_count: int
    unpaid_invoice_count: int
    total_invoiced: Decimal
    total_paid: Decimal
    outstanding: Decimal


class PortalActivityItem(BaseModel):
    id: str
    type: str
    message: str
    created_at: datetime


class PortalTaskOut(BaseModel):
    id: UUID
    project_id: UUID
    project_title: str | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    due_date: datetime | None = None
    created_at: datetime


class PortalMilestoneOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None = None
    due_date: date | None = None
    status: str
    sort_order: int


class PortalFileOut(BaseModel):
    id: UUID
    project_id: UUID | None = None
    project_title: str | None = None
    filename: str
    content_type: str
    size: int
    folder: str
    folder_label: str
    kind: str
    source: str
    created_at: datetime


class PortalApprovalOut(BaseModel):
    id: UUID
    project_id: UUID | None = None
    project_title: str | None = None
    document_id: UUID | None = None
    document_filename: str | None = None
    title: str
    description: str | None = None
    kind: str
    kind_label: str
    status: str
    client_comment: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class PortalApprovalDecision(BaseModel):
    status: str = Field(pattern="^(approved|changes_requested|rejected)$")
    client_comment: str | None = None


class PortalMessageOut(BaseModel):
    id: UUID
    project_id: UUID | None = None
    project_title: str | None = None
    sender_side: str
    sender_name: str | None = None
    body: str
    is_read: bool
    created_at: datetime


class PortalMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    project_id: UUID | None = None


class PortalProjectDetail(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    status: str
    start_date: date | None = None
    end_date: date | None = None
    task_total: int
    task_done: int
    progress_percent: int
    milestones: list[PortalMilestoneOut]
    tasks: list[PortalTaskOut]
    files: list[PortalFileOut]
    approvals: list[PortalApprovalOut]


# Staff-facing create schemas
class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: str = "pending"
    sort_order: int = 0


class MilestoneUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: date | None = None
    status: str | None = None
    sort_order: int | None = None


class ApprovalCreate(BaseModel):
    client_id: UUID
    project_id: UUID | None = None
    document_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    kind: str = Field(pattern="^(design|video|document|deliverable)$")


class StaffClientMessageCreate(BaseModel):
    client_id: UUID
    body: str = Field(min_length=1, max_length=5000)
    project_id: UUID | None = None
