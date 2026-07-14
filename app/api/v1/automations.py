from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_permission, require_staff
from app.db.session import get_db
from app.models.automation import Automation, AutomationRun
from app.models.user import User
from app.schemas.automation import (
    AUTOMATION_ACTIONS,
    AUTOMATION_TRIGGERS,
    VALID_ACTIONS,
    VALID_TRIGGERS,
    AutomationCreate,
    AutomationOut,
    AutomationRunOut,
    AutomationUpdate,
)
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/automations", tags=["automations"])


@router.get("/catalog")
async def automation_catalog(current: CurrentUser = Depends(require_staff)):
    return {"triggers": AUTOMATION_TRIGGERS, "actions": AUTOMATION_ACTIONS}


@router.get("", response_model=list[AutomationOut])
async def list_automations(
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Automation)
        .where(Automation.company_id == current.company_id)
        .order_by(Automation.updated_at.desc())
    )
    return [await _automation_out(db, a) for a in result.scalars().all()]


@router.post("", response_model=AutomationOut, status_code=status.HTTP_201_CREATED)
async def create_automation(
    body: AutomationCreate,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    if body.trigger_key not in VALID_TRIGGERS:
        raise HTTPException(status_code=400, detail="Invalid trigger")
    actions = _normalize_actions(body.actions)
    automation = Automation(
        company_id=current.company_id,
        created_by_id=current.id,
        name=body.name,
        description=body.description,
        trigger_key=body.trigger_key,
        actions=actions,
        is_active=body.is_active,
    )
    db.add(automation)
    await db.flush()
    return await _automation_out(db, automation)


@router.get("/{automation_id}", response_model=AutomationOut)
async def get_automation(
    automation_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    automation = await _get_automation(db, automation_id, current.company_id)
    return await _automation_out(db, automation)


@router.patch("/{automation_id}", response_model=AutomationOut)
async def update_automation(
    automation_id: UUID,
    body: AutomationUpdate,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    automation = await _get_automation(db, automation_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "trigger_key" in data and data["trigger_key"] not in VALID_TRIGGERS:
        raise HTTPException(status_code=400, detail="Invalid trigger")
    if "actions" in data and data["actions"] is not None:
        data["actions"] = _normalize_actions(data["actions"])
    for k, v in data.items():
        setattr(automation, k, v)
    await db.flush()
    return await _automation_out(db, automation)


@router.post("/{automation_id}/toggle", response_model=AutomationOut)
async def toggle_automation(
    automation_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    automation = await _get_automation(db, automation_id, current.company_id)
    automation.is_active = not automation.is_active
    await db.flush()
    return await _automation_out(db, automation)


@router.delete("/{automation_id}", response_model=MessageResponse)
async def delete_automation(
    automation_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    automation = await _get_automation(db, automation_id, current.company_id)
    await db.delete(automation)
    return MessageResponse(message="Automation deleted")


@router.get("/{automation_id}/runs", response_model=list[AutomationRunOut])
async def list_runs(
    automation_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_automations")),
    db: AsyncSession = Depends(get_db),
):
    await _get_automation(db, automation_id, current.company_id)
    result = await db.execute(
        select(AutomationRun)
        .where(
            AutomationRun.automation_id == automation_id,
            AutomationRun.company_id == current.company_id,
        )
        .order_by(AutomationRun.created_at.desc())
        .limit(50)
    )
    return list(result.scalars().all())


def _normalize_actions(actions) -> list[dict]:
    normalized: list[dict] = []
    for action in actions:
        data = action.model_dump() if hasattr(action, "model_dump") else dict(action)
        action_type = data.get("type")
        if action_type not in VALID_ACTIONS:
            raise HTTPException(status_code=400, detail=f"Invalid action: {action_type}")
        normalized.append(
            {
                "id": data.get("id") or str(uuid4()),
                "type": action_type,
                "config": data.get("config") or {},
            }
        )
    return normalized


async def _get_automation(db: AsyncSession, automation_id: UUID, company_id: UUID) -> Automation:
    result = await db.execute(
        select(Automation).where(Automation.id == automation_id, Automation.company_id == company_id)
    )
    automation = result.scalar_one_or_none()
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")
    return automation


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _automation_out(db: AsyncSession, automation: Automation) -> AutomationOut:
    label = next((t["label"] for t in AUTOMATION_TRIGGERS if t["key"] == automation.trigger_key), automation.trigger_key)
    return AutomationOut(
        id=automation.id,
        company_id=automation.company_id,
        created_by_id=automation.created_by_id,
        created_by_name=await _creator_name(db, automation.created_by_id),
        name=automation.name,
        description=automation.description,
        trigger_key=automation.trigger_key,
        trigger_label=label,
        actions=list(automation.actions or []),
        is_active=automation.is_active,
        created_at=automation.created_at,
        updated_at=automation.updated_at,
    )
