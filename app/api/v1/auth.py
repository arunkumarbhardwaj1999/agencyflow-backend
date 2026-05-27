from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import CurrentUser, get_current_user
from app.core.security import generate_reset_token, hash_password, hash_token
from app.db.session import get_db
from app.integrations.email import send_password_reset_email
from app.integrations.supabase_auth import create_user as supabase_create_user
from app.integrations.supabase_auth import refresh_session, sign_in, update_password as supabase_update_password
from app.models.company import Company
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Role
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.schemas.common import MessageResponse, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _ensure_supabase_configured() -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key or not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=500,
            detail="Supabase is not configured. Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET.",
        )


def _tokens_from_session(session: dict) -> TokenResponse:
    return TokenResponse(
        access_token=session["access_token"],
        refresh_token=session["refresh_token"],
        token_type=session.get("token_type", "bearer"),
    )


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
    _ensure_supabase_configured()

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

    supabase_user_id = await supabase_create_user(body.email, body.password)

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
        supabase_user_id=supabase_user_id,
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

    session = await sign_in(body.email, body.password)
    return _tokens_from_session(session)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    _ensure_supabase_configured()

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if not user.supabase_user_id:
        raise HTTPException(status_code=400, detail="Account is not linked to Supabase Auth yet")

    session = await sign_in(body.email, body.password)
    return _tokens_from_session(session)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    _ensure_supabase_configured()
    session = await refresh_session(body.refresh_token)
    return _tokens_from_session(session)


@router.post("/logout", response_model=MessageResponse)
async def logout(_: CurrentUser = Depends(get_current_user)):
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserOut)
async def me(current: CurrentUser = Depends(get_current_user)):
    return _user_out(current.user, current.role_name)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active.is_(True)))
    user = result.scalar_one_or_none()

    reset_token: str | None = None
    if user:
        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        reset_token = generate_reset_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(reset_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )
        reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"
        await send_password_reset_email(user.email, reset_url)

    return ForgotPasswordResponse(
        message="If that email exists, a reset link has been sent.",
        reset_token=reset_token if settings.debug else None,
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(body.token)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(UTC),
        )
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    if user.supabase_user_id:
        await supabase_update_password(user.supabase_user_id, body.new_password)

    token_row.used_at = datetime.now(UTC)
    return MessageResponse(message="Password reset successfully")
