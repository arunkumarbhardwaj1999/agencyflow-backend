"""Duplicate lead detection by email, phone, and company name."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits or None


def normalize_company_name(name: str | None) -> str | None:
    if not name:
        return None
    value = " ".join(name.strip().lower().split())
    return value or None


def _match_fields(
    lead: Lead,
    *,
    email: str | None,
    phone: str | None,
    company_name: str | None,
) -> list[str]:
    fields: list[str] = []
    lead_email = normalize_email(lead.email)
    lead_phone = normalize_phone(lead.phone)
    lead_company = normalize_company_name(lead.company_name)

    if email and lead_email and lead_email == email:
        fields.append("email")
    if phone and lead_phone and lead_phone == phone:
        fields.append("phone")
    if company_name and lead_company and lead_company == company_name:
        fields.append("company_name")
    return fields


async def find_duplicate_leads(
    db: AsyncSession,
    company_id: UUID,
    *,
    email: str | None = None,
    phone: str | None = None,
    company_name: str | None = None,
    exclude_lead_id: UUID | None = None,
) -> list[tuple[Lead, list[str]]]:
    norm_email = normalize_email(email)
    norm_phone = normalize_phone(phone)
    norm_company = normalize_company_name(company_name)

    if not any([norm_email, norm_phone, norm_company]):
        return []

    clauses = []
    if norm_email:
        clauses.append(Lead.email.ilike(norm_email))
    if norm_phone:
        digits = norm_phone
        clauses.append(Lead.phone.ilike(f"%{digits[-10:]}%"))
    if norm_company:
        clauses.append(Lead.company_name.ilike(norm_company))

    q = select(Lead).where(Lead.company_id == company_id, or_(*clauses))
    if exclude_lead_id:
        q = q.where(Lead.id != exclude_lead_id)

    result = await db.execute(q.order_by(Lead.created_at.desc()))
    leads = list(result.scalars().all())

    matches: list[tuple[Lead, list[str]]] = []
    for lead in leads:
        fields = _match_fields(
            lead,
            email=norm_email,
            phone=norm_phone,
            company_name=norm_company,
        )
        if fields:
            matches.append((lead, fields))
    return matches
