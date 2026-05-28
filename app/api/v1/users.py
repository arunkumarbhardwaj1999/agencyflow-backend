from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, require_permission
from app.core.plans import assert_can_add_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User
from app.schemas.user import StaffCreateRequest, StaffOut, StaffUpdateRequest

router = APIRouter(prefix="/users", tags=["users"])


def _to_out(user: User) -> StaffOut:
    role_name = user.role.name if user.role else "employee"
    return StaffOut(
        id=user.id,
        company_id=user.company_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone=user.phone,
        role=role_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@router.get("", response_model=list[StaffOut])
async def list_staff(
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.company_id == current.company_id)
        .order_by(User.created_at.desc())
    )
    return [_to_out(u) for u in result.scalars().all()]


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: StaffCreateRequest,
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    role_result = await db.execute(select(Role).where(Role.name == body.role))
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role")

    email_exists = await db.execute(select(User).where(User.email == body.email))
    if email_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    await assert_can_add_user(db, current.company_id)

    user = User(
        company_id=current.company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hash_password(body.password),
        phone=body.phone,
        role_id=role.id,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user, ["role"])
    return _to_out(user)


@router.patch("/{user_id}", response_model=StaffOut)
async def update_staff(
    user_id: UUID,
    body: StaffUpdateRequest,
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id, User.company_id == current.company_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Owner cannot deactivate self")

    data = body.model_dump(exclude_unset=True)
    role_name = data.pop("role", None)
    if role_name:
        role_result = await db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role_id = role.id

    for key, value in data.items():
        setattr(user, key, value)

    await db.flush()
    await db.refresh(user, ["role"])
    return _to_out(user)
