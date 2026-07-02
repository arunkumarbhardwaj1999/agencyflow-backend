from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: UUID
    project_id: UUID | None
    invoice_id: UUID | None
    filename: str
    content_type: str
    size: int
    kind: str
    created_at: datetime


class LogoOut(BaseModel):
    logo: str
