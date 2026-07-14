from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: UUID
    project_id: UUID | None
    invoice_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    filename: str
    content_type: str
    size: int
    kind: str
    created_at: datetime


class DealAttachmentOut(ORMModel):
    id: UUID
    deal_id: UUID
    filename: str
    content_type: str
    size: int
    kind: str
    is_proposal: bool = False
    uploaded_by_id: UUID | None
    uploaded_by_name: str | None = None
    uploaded_at: datetime
    preview_url: str | None = None
    download_url: str | None = None
    is_previewable: bool = False


class LeadAttachmentOut(ORMModel):
    id: UUID
    lead_id: UUID
    filename: str
    content_type: str
    size: int
    uploaded_by_id: UUID | None
    uploaded_by_name: str | None = None
    uploaded_at: datetime
    preview_url: str | None = None
    download_url: str | None = None
    is_previewable: bool = False


class LogoOut(BaseModel):
    logo: str | None = None


class ClientDocumentOut(ORMModel):
    id: UUID
    client_id: UUID
    folder: str
    folder_label: str
    filename: str
    content_type: str
    size: int
    uploaded_by_id: UUID | None
    uploaded_by_name: str | None = None
    uploaded_at: datetime
    preview_url: str | None = None
    download_url: str | None = None
    is_previewable: bool = False


class ClientDocumentUpdate(BaseModel):
    filename: str | None = None
    folder: str | None = None


class DocumentFolderSuggestRequest(BaseModel):
    filename: str
    content_type: str | None = None


class DocumentFolderSuggestOut(BaseModel):
    folder: str
    folder_label: str
    reason: str
    confidence: float

