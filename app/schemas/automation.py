from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

AUTOMATION_TRIGGERS = [
    {"key": "lead_created", "label": "Lead Created", "description": "When a new lead is added"},
    {"key": "deal_won", "label": "Deal Won", "description": "When a deal is marked won"},
    {"key": "invoice_paid", "label": "Invoice Paid", "description": "When an invoice is paid"},
    {"key": "task_completed", "label": "Task Completed", "description": "When a task is marked done"},
    {"key": "project_completed", "label": "Project Completed", "description": "When a project is finished"},
    {"key": "task_overdue", "label": "Task Overdue", "description": "When a task is past due"},
]

AUTOMATION_ACTIONS = [
    {"key": "assign_manager", "label": "Assign Manager", "description": "Assign entity to a manager"},
    {"key": "send_email", "label": "Send Email", "description": "Send an email notification"},
    {"key": "send_whatsapp", "label": "Send WhatsApp", "description": "Send WhatsApp / SMS message"},
    {"key": "create_task", "label": "Create Task", "description": "Create a follow-up task"},
    {"key": "update_status", "label": "Update Status", "description": "Change entity status"},
    {"key": "wait", "label": "Wait", "description": "Wait N days before next action (logged)"},
    {"key": "notify_manager", "label": "Notify Manager", "description": "Notify company managers"},
    {"key": "notify_owner", "label": "Notify Owner", "description": "Notify workspace owner"},
    {"key": "webhook", "label": "Webhook / API", "description": "Call an external URL"},
]

VALID_TRIGGERS = {t["key"] for t in AUTOMATION_TRIGGERS}
VALID_ACTIONS = {a["key"] for a in AUTOMATION_ACTIONS}


class AutomationActionBlock(BaseModel):
    id: str
    type: str
    config: dict = Field(default_factory=dict)


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    trigger_key: str
    actions: list[AutomationActionBlock] = Field(default_factory=list)
    is_active: bool = True


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    trigger_key: str | None = None
    actions: list[AutomationActionBlock] | None = None
    is_active: bool | None = None


class AutomationOut(ORMModel):
    id: UUID
    company_id: UUID
    created_by_id: UUID | None
    created_by_name: str | None = None
    name: str
    description: str | None
    trigger_key: str
    trigger_label: str
    actions: list[dict]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AutomationRunOut(ORMModel):
    id: UUID
    automation_id: UUID
    trigger_key: str
    entity_type: str | None
    entity_id: UUID | None
    status: str
    result: dict
    created_at: datetime
