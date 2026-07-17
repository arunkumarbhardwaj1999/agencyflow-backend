from datetime import datetime, timedelta
from app.core.utc import UTC
import secrets
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, get_current_user
from app.core.email import (
    send_account_confirm_email,
    send_owner_credentials_email,
    send_password_reset_email,
)
from app.core.otp import generate_otp_code, hash_otp, send_otp_to_email, send_otp_to_phone
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_reset_token,
    generate_temporary_password,
    hash_password,
    hash_token,
    token_subject_uuid,
    verify_password,
)
from app.core.usernames import find_user_by_login, unique_username, username_from_email
from app.core.google_auth import GoogleAuthError, verify_google_id_token
from app.core.plans import get_starter_plan
from app.db.session import get_db
from app.models.company import Company
from app.models.password_reset_token import PasswordResetToken
from app.models.phone_otp import PhoneOtp
from app.models.role import Role
from app.models.user import User
from app.schemas.auth import (
    AcceptInviteGoogleRequest,
    AcceptInviteRequest,
    ChangePasswordRequest,
    ConfirmAccountPreview,
    ConfirmAccountRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleLoginRequest,
    GoogleRegisterPendingResponse,
    GoogleRegisterRequest,
    InvitePreviewResponse,
    InviteRejectRequest,
    InviteSetupRequest,
    InviteSetupResponse,
    InviteVerifyEmailRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    SendOtpRequest,
    SendOtpResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.schemas.common import MessageResponse, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:100]
    return slug if len(slug) >= 2 else "workspace"


async def _unique_slug(db: AsyncSession, company_name: str, preferred: str | None = None) -> str:
    base = _slugify(preferred or company_name)
    candidate = base
    n = 2
    while True:
        exists = await db.execute(select(Company).where(Company.slug == candidate))
        if not exists.scalar_one_or_none():
            return candidate
        suffix = f"-{n}"
        candidate = f"{base[: 100 - len(suffix)]}{suffix}"
        n += 1


def _user_out(user: User, role_name: str) -> UserOut:
    return UserOut(
        id=user.id,
        company_id=user.company_id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        email=user.email,
        phone=user.phone,
        role=role_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


def _tokens_for_user(user: User, role_name: str) -> TokenResponse:
    access = create_access_token(
        str(user.id),
        extra={"company_id": str(user.company_id) if user.company_id else None, "role": role_name},
    )
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


async def _invite_from_token(db: AsyncSession, token: str) -> tuple[PasswordResetToken, User]:
    token_hash = hash_token(token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row or token_row.used_at is not None or token_row.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invalid or expired invite")

    user_result = await db.execute(
        select(User).options(selectinload(User.role), selectinload(User.company)).where(
            User.id == token_row.user_id
        )
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return token_row, user


async def _get_pending_owner(db: AsyncSession, registration_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == registration_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Registration not found")
    if user.is_verified:
        raise HTTPException(status_code=400, detail="Account already confirmed")
    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one_or_none()
    if not role or role.name != "owner":
        raise HTTPException(status_code=400, detail="Invalid registration")
    return user


async def _send_confirm_email(
    user: User,
    db: AsyncSession,
) -> tuple[bool, str | None, str | None]:
    confirm_token = generate_reset_token()
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(confirm_token),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    await db.flush()
    confirm_link = f"{settings.frontend_url}/confirm-account?token={confirm_token}"
    email_ok, email_err = await send_account_confirm_email(user.email, user.first_name, confirm_link)
    expose_link = confirm_link if (not email_ok or settings.debug) else None
    return email_ok, email_err, expose_link


def _register_pending_response(
    user: User,
    *,
    email_sent: bool,
    email_error: str | None,
    confirm_link: str | None,
) -> GoogleRegisterPendingResponse:
    return GoogleRegisterPendingResponse(
        registration_id=user.id,
        email=user.email,
        first_name=user.first_name,
        email_sent=email_sent,
        email_error=email_error,
        confirm_link=confirm_link,
    )


@router.post("/register", response_model=GoogleRegisterPendingResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.lower()
    email_exists = await db.execute(select(User).where(User.email == email))
    existing = email_exists.scalar_one_or_none()
    if existing:
        if not existing.is_verified:
            email_ok, email_err, confirm_link = await _send_confirm_email(existing, db)
            return _register_pending_response(
                existing, email_sent=email_ok, email_error=email_err, confirm_link=confirm_link
            )
        raise HTTPException(status_code=400, detail="Email already registered")

    owner_role = await db.execute(select(Role).where(Role.name == "owner"))
    role = owner_role.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=500, detail="System roles not seeded. Run: python -m scripts.seed_roles")

    username = await unique_username(db, username_from_email(email))
    workspace_name = f"{body.first_name} {body.last_name or ''}".strip() or username.replace("_", " ").title()
    slug = await _unique_slug(db, workspace_name, username)
    phone = "".join(c for c in body.phone if c.isdigit()) if body.phone else None

    starter = await get_starter_plan(db)
    company = Company(
        company_name=workspace_name,
        slug=slug,
        email=email,
        subscription_plan_id=starter.id if starter else None,
    )
    db.add(company)
    await db.flush()

    user = User(
        company_id=company.id,
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip() if body.last_name else None,
        username=username,
        email=email,
        phone=phone,
        password_hash=hash_password(body.password),
        role_id=role.id,
        is_verified=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    email_ok, email_err, confirm_link = await _send_confirm_email(user, db)
    return _register_pending_response(
        user, email_sent=email_ok, email_error=email_err, confirm_link=confirm_link
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await find_user_by_login(db, body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Confirm your account via email first.")
    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    access = create_access_token(
        str(user.id),
        extra={"company_id": str(user.company_id) if user.company_id else None, "role": role.name},
    )
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/google", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = await verify_google_id_token(body.credential)
    except GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    email = payload["email"].lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found for this Google email. Please register first.",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if not user.is_verified:
        if user.invited_by_id is not None:
            raise HTTPException(
                status_code=403,
                detail="This email has a pending team invite. Open the invite email and join via the link — do not use the main login page.",
            )
        raise HTTPException(
            status_code=403,
            detail="Confirm your account via email first. Check your inbox (and spam) for the confirmation link.",
        )

    picture = payload.get("picture")
    if picture and not user.avatar:
        user.avatar = picture

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    return _tokens_for_user(user, role.name)


@router.post("/google/register", response_model=GoogleRegisterPendingResponse, status_code=status.HTTP_201_CREATED)
async def google_register(
    body: GoogleRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start owner signup with Google — email confirmation required before login."""
    try:
        payload = await verify_google_id_token(body.credential)
    except GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    email = payload["email"].lower()
    existing = await db.execute(select(User).where(User.email == email))
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(
                status_code=400,
                detail="This Google email is already registered. Sign in instead.",
            )
        email_ok, email_err, confirm_link = await _send_confirm_email(existing_user, db)
        return _register_pending_response(
            existing_user, email_sent=email_ok, email_error=email_err, confirm_link=confirm_link
        )

    owner_role = await db.execute(select(Role).where(Role.name == "owner"))
    role = owner_role.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=500, detail="System roles not seeded")

    username = await unique_username(db, username_from_email(email))
    workspace_name = username.replace("_", " ").title()
    slug = await _unique_slug(db, workspace_name, username)
    given_name = (payload.get("given_name") or "").strip() or workspace_name
    family_name = (payload.get("family_name") or "").strip() or None

    starter = await get_starter_plan(db)
    company = Company(
        company_name=workspace_name,
        slug=slug,
        email=email,
        subscription_plan_id=starter.id if starter else None,
    )
    db.add(company)
    await db.flush()

    user = User(
        company_id=company.id,
        first_name=given_name,
        last_name=family_name,
        username=username,
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        avatar=payload.get("picture"),
        role_id=role.id,
        is_verified=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    email_ok, email_err, confirm_link = await _send_confirm_email(user, db)
    return _register_pending_response(
        user, email_sent=email_ok, email_error=email_err, confirm_link=confirm_link
    )


@router.post("/register/send-otp", response_model=SendOtpResponse)
async def register_send_otp(
    body: SendOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_pending_owner(db, body.registration_id)
    phone = "".join(c for c in body.phone if c.isdigit())
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Enter a valid phone number")

    code = generate_otp_code()
    await db.execute(delete(PhoneOtp).where(PhoneOtp.user_id == user.id))
    db.add(
        PhoneOtp(
            user_id=user.id,
            channel="phone",
            destination=phone,
            otp_hash=hash_otp(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.flush()
    sent, send_err = await send_otp_to_phone(phone, code, recipient_name=user.first_name or "there")
    if not sent:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not send OTP by SMS. Set SMS_PROVIDER (twilio or msg91) and API keys in backend .env."
                + (f" ({send_err})" if settings.debug and send_err else "")
            ),
        )

    dev_otp = code if settings.debug else None
    message = "Verification code sent by SMS to your mobile number."
    if settings.debug and dev_otp:
        message += " If SMS is delayed (complete MSG91 KYC), use the code shown below."
    return SendOtpResponse(
        message=message,
        dev_otp=dev_otp,
    )


@router.post("/register/verify-otp", response_model=VerifyOtpResponse)
async def register_verify_otp(
    body: VerifyOtpRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_pending_owner(db, body.registration_id)
    phone = "".join(c for c in body.phone if c.isdigit())
    result = await db.execute(
        select(PhoneOtp)
        .where(PhoneOtp.user_id == user.id, PhoneOtp.verified_at.is_(None))
        .order_by(PhoneOtp.created_at.desc())
    )
    otp_row = result.scalar_one_or_none()
    if not otp_row or otp_row.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="OTP expired. Request a new code.")
    if otp_row.otp_hash != hash_otp(body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    otp_row.verified_at = datetime.now(UTC)
    user.phone = phone

    confirm_token = generate_reset_token()
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(confirm_token),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    await db.flush()

    confirm_link = f"{settings.frontend_url}/confirm-account?token={confirm_token}"
    await send_account_confirm_email(user.email, user.first_name, confirm_link)
    return VerifyOtpResponse(
        message="Phone verified. Check your email to confirm your account.",
        email=user.email,
    )


@router.get("/confirm-account", response_model=ConfirmAccountPreview)
async def confirm_account_preview(token: str, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row or token_row.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation link")

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return ConfirmAccountPreview(
        email=user.email,
        first_name=user.first_name,
        already_confirmed=user.is_verified,
    )


@router.post("/confirm-account", response_model=TokenResponse)
async def confirm_account(body: ConfirmAccountRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(body.token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid confirmation link")
    if token_row.expires_at <= now:
        raise HTTPException(status_code=400, detail="Confirmation link expired")

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()

    if user.is_verified:
        return _tokens_for_user(user, role.name)

    user.is_verified = True
    user.must_change_password = False
    token_row.used_at = now
    return _tokens_for_user(user, role.name)


@router.get("/invite/preview", response_model=InvitePreviewResponse)
async def invite_preview(
    token: str,
    email: str,
    db: AsyncSession = Depends(get_db),
):
    _, user = await _invite_from_token(db, token)
    if user.email.lower() != email.strip().lower():
        raise HTTPException(status_code=400, detail="Invite does not match this email")

    workspace = user.company.company_name if user.company else "AgencyFlow"
    inviter_name = workspace
    inviter_email: str | None = None
    if user.invited_by_id:
        inv_result = await db.execute(select(User).where(User.id == user.invited_by_id))
        inviter = inv_result.scalar_one_or_none()
        if inviter:
            inviter_name = f"{inviter.first_name} {inviter.last_name or ''}".strip()
            inviter_email = inviter.email

    return InvitePreviewResponse(
        workspace=workspace,
        invited_email=user.email,
        inviter_name=inviter_name,
        inviter_email=inviter_email,
        role=user.role.name if user.role else "employee",
        first_name=user.first_name,
        last_name=user.last_name,
    )


@router.post("/invite/setup", response_model=InviteSetupResponse)
async def invite_setup(
    body: InviteSetupRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row, user = await _invite_from_token(db, body.token)
    if user.is_verified:
        raise HTTPException(status_code=400, detail="Invite already accepted")

    user.first_name = body.first_name.strip()
    user.last_name = body.last_name.strip() if body.last_name else None
    user.password_hash = hash_password(body.password)
    user.must_change_password = False

    code = generate_otp_code()
    await db.execute(delete(PhoneOtp).where(PhoneOtp.user_id == user.id))
    db.add(
        PhoneOtp(
            user_id=user.id,
            channel="email",
            destination=user.email.lower(),
            otp_hash=hash_otp(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.flush()

    workspace = user.company.company_name if user.company else "AgencyFlow"
    await send_otp_to_email(user.email, code, workspace)

    return InviteSetupResponse(
        message="Verification code sent to your email.",
        email=user.email,
    )


@router.post("/invite/verify-email", response_model=TokenResponse)
async def invite_verify_email(body: InviteVerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    token_row, user = await _invite_from_token(db, body.token)

    result = await db.execute(
        select(PhoneOtp)
        .where(
            PhoneOtp.user_id == user.id,
            PhoneOtp.channel == "email",
            PhoneOtp.verified_at.is_(None),
        )
        .order_by(PhoneOtp.created_at.desc())
    )
    otp_row = result.scalar_one_or_none()
    if not otp_row or otp_row.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="OTP expired. Go back and proceed again.")
    if otp_row.otp_hash != hash_otp(body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    otp_row.verified_at = datetime.now(UTC)
    user.is_verified = True
    token_row.used_at = datetime.now(UTC)

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    return _tokens_for_user(user, role.name)


@router.post("/invite/accept-google", response_model=TokenResponse)
async def accept_invite_google(body: AcceptInviteGoogleRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = await verify_google_id_token(body.credential)
    except GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token_hash = hash_token(body.token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row or token_row.used_at is not None or token_row.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invalid or expired invite")

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    google_email = payload["email"].lower()
    if google_email != user.email.lower():
        raise HTTPException(
            status_code=400,
            detail="Sign in with the Google account that matches the invited email.",
        )

    user.is_verified = True
    user.avatar = payload.get("picture") or user.avatar
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    token_row.used_at = now

    role_result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = role_result.scalar_one()
    return _tokens_for_user(user, role.name)


@router.post("/invite/reject", response_model=MessageResponse)
async def invite_reject(body: InviteRejectRequest, db: AsyncSession = Depends(get_db)):
    token_row, user = await _invite_from_token(db, body.token)
    if user.is_verified:
        raise HTTPException(status_code=400, detail="Invite already accepted")
    user.is_active = False
    token_row.used_at = datetime.now(UTC)
    return MessageResponse(message="Invitation declined")


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


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = current.user
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a different password")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await db.flush()
    return MessageResponse(message="Password updated successfully")


@router.post("/dismiss-password-prompt", response_model=MessageResponse)
async def dismiss_password_prompt(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current.user.must_change_password = False
    await db.flush()
    return MessageResponse(message="OK")


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
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
        reset_link = f"{settings.frontend_url}/reset-password?token={reset_token}"
        background.add_task(send_password_reset_email, user.email, reset_link)

    # In production (email configured) the token is delivered only by email.
    # In mock mode it's returned so the flow can be tested without a mailbox.
    expose_token = reset_token if not settings.email_enabled else None
    return ForgotPasswordResponse(
        message="If that email exists, a reset link has been sent.",
        reset_token=expose_token,
        email=user.email if user and expose_token else None,
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(body.token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if token_row.used_at is not None:
        raise HTTPException(
            status_code=400,
            detail="This reset token was already used. Generate a new token on the forgot password page.",
        )
    if token_row.expires_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Reset token expired. Generate a new token (valid for 30 minutes).",
        )

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)

    token_row.used_at = datetime.now(UTC)
    return MessageResponse(message="Password reset successfully")


@router.post("/accept-invite", response_model=MessageResponse)
async def accept_invite(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(body.token.strip())
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid invite token")
    if token_row.used_at is not None:
        raise HTTPException(status_code=400, detail="This invite was already accepted")
    if token_row.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invite expired. Ask your admin for a new invite.")

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    user.is_verified = True
    token_row.used_at = datetime.now(UTC)
    return MessageResponse(message="Invite accepted — you can sign in now")
