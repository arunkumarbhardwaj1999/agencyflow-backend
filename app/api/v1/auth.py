import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_subject_uuid,
    verify_password,
)
from app.db.session import get_db
from app.models.company import Company
from app.models.role import Role
from app.models.user import User
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, RefreshRequest, RegisterRequest
from app.schemas.common import MessageResponse, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User, role_name: str) -> UserOut:
    return UserOut(
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


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    slug_exists = await db.execute(select(Company).where(Company.slug == body.slug))
    if slug_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Workspace slug already taken")

    email_exists = await db.execute(select(User).where(User.email == body.email))
    if email_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    owner_role = await db.execute(select(Role).where(Role.name == "owner"))
    role = owner_role.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=500, detail="System roles not seeded. Run: python -m scripts.seed_roles")

    company = Company(
        company_name=body.company_name,
        slug=body.slug.lower(),
        email=body.company_email,
        phone=body.phone,
        address=body.address,
        gst_number=body.gst_number,
    )
    db.add(company)
    await db.flush()

    user = User(
        company_id=company.id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hash_password(body.password),
        phone=body.phone,
        role_id=role.id,
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    access = create_access_token(
        str(user.id),
        extra={"company_id": str(company.id), "role": "owner"},
    )
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    access = create_access_token(
        str(user.id),
        extra={"company_id": str(user.company_id) if user.company_id else None, "role": role.name},
    )
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        user_id = token_subject_uuid(payload)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token") from None

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    access = create_access_token(
        str(user.id),
        extra={"company_id": str(user.company_id) if user.company_id else None, "role": role.name},
    )
    new_refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout", response_model=MessageResponse)
async def logout(_: CurrentUser = Depends(get_current_user)):
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserOut)
async def me(current: CurrentUser = Depends(get_current_user)):
    return _user_out(current.user, current.role_name)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    await db.execute(select(User).where(User.email == body.email))
    return MessageResponse(message="If that email exists, a reset link has been sent.")
