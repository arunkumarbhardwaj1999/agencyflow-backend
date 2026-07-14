from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_staff
from app.core.record_360 import ENTITY_TYPES, build_record_360
from app.db.session import get_db
from app.models.task import Task
from app.schemas.record_360 import Record360View

router = APIRouter(prefix="/records", tags=["records"])


@router.get("/{entity_type}/{entity_id}", response_model=Record360View)
async def get_record_360(
    entity_type: str,
    entity_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """360° view — all related data for a Lead, Deal, Client, or Project in one response."""
    normalized = entity_type.strip().lower()
    if normalized not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity type '{entity_type}'. Use: lead, deal, client, project",
        )
    if current.role_name == "employee" and not current.can("manage_projects"):
        if normalized != "project":
            raise HTTPException(status_code=403, detail="Employees can only open assigned projects")
        result = await db.execute(
            select(Task.id)
            .where(
                Task.company_id == current.company_id,
                Task.project_id == entity_id,
                Task.assigned_to == current.id,
            )
            .limit(1)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="You can only view assigned projects")
    return await build_record_360(db, current.company_id, current.id, normalized, entity_id)
