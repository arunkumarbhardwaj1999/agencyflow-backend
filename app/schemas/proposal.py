from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

PROPOSAL_TEMPLATES = [
    {
        "key": "website",
        "label": "Website",
        "description": "Web design, development, SEO, and hosting",
        "default_services": ["Website", "SEO", "Hosting"],
    },
    {
        "key": "marketing",
        "label": "Marketing",
        "description": "Digital marketing, ads, and content",
        "default_services": ["Social Media", "Google Ads", "Content"],
    },
    {
        "key": "branding",
        "label": "Branding",
        "description": "Logo, identity, and brand guidelines",
        "default_services": ["Logo Design", "Brand Guidelines", "Stationery"],
    },
    {
        "key": "custom",
        "label": "Custom",
        "description": "Start from a blank proposal",
        "default_services": [],
    },
]

PROPOSAL_STATUSES = {"draft", "sent", "approved", "rejected"}


class ProposalTemplateOut(BaseModel):
    key: str
    label: str
    description: str
    default_services: list[str]


class ProposalCreate(BaseModel):
    template_key: str = "website"
    title: str = Field(min_length=1, max_length=255)
    client_id: UUID | None = None
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    project_value: float = 0
    services: list[str] = Field(default_factory=list)
    overview: str | None = None
    timeline: str | None = None
    deliverables: str | None = None
    scope: str | None = None
    pricing: str | None = None
    terms: str | None = None
    conclusion: str | None = None


class ProposalUpdate(BaseModel):
    template_key: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    client_id: UUID | None = None
    project_value: float | None = None
    services: list[str] | None = None
    overview: str | None = None
    timeline: str | None = None
    deliverables: str | None = None
    scope: str | None = None
    pricing: str | None = None
    terms: str | None = None
    conclusion: str | None = None
    status: str | None = None


class ProposalOut(ORMModel):
    id: UUID
    company_id: UUID
    client_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    created_by_id: UUID | None
    created_by_name: str | None = None
    client_name: str | None = None
    template_key: str
    template_label: str
    title: str
    project_value: float
    services: list[str]
    overview: str | None
    timeline: str | None
    deliverables: str | None
    scope: str | None
    pricing: str | None
    terms: str | None
    conclusion: str | None
    status: str
    sent_at: datetime | None
    approved_at: datetime | None
    contract_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ProposalAIDraftRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    template_key: str = "website"
    client_id: UUID | None = None
    lead_id: UUID | None = None
    deal_id: UUID | None = None


class ProposalAIDraftOut(BaseModel):
    title: str
    project_value: float
    services: list[str]
    overview: str
    timeline: str
    deliverables: str
    scope: str
    pricing: str
    terms: str
    conclusion: str
    mode: str
