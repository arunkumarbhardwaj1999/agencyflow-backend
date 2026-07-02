from uuid import UUID

from pydantic import BaseModel, Field


class LeadAIRequest(BaseModel):
    lead_id: UUID


class ProjectAIRequest(BaseModel):
    project_id: UUID


class InvoiceAIRequest(BaseModel):
    invoice_id: UUID


class TaskAIRequest(BaseModel):
    task_id: UUID


class ClientAIRequest(BaseModel):
    client_id: UUID
    project_id: UUID | None = None


class AIStreamRequest(BaseModel):
    action: str = Field(
        description="draft-email | summarize-project | suggest-followups | draft-invoice-email | polish-task | draft-client-welcome"
    )
    lead_id: UUID | None = None
    project_id: UUID | None = None
    invoice_id: UUID | None = None
    task_id: UUID | None = None
    client_id: UUID | None = None


class AIResponse(BaseModel):
    content: str
    mode: str  # "live" | "mock"


class AIStreamChunk(BaseModel):
    chunk: str
    done: bool = False
    mode: str = "live"
