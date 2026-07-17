from datetime import datetime, timedelta
from app.core.utc import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.email import send_staff_invite_email
from app.core.plans import assert_can_add_user
from app.core.usernames import unique_username, username_from_email
from app.core.security import generate_reset_token, hash_password, hash_token
from app.db.session import get_db
from app.models.company import Company
from app.models.group import Group
from app.models.group_member import GroupMember
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Role
from app.models.user import User
from app.schemas.user import (
    GroupCreateRequest,
    GroupMemberOut,
    GroupOut,
    MemberOut,
    StaffCreateRequest,
    StaffInviteRequest,
    StaffInviteResponse,
    StaffOut,
    StaffUpdateRequest,
)

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()


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


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight roster of active staff for assignment dropdowns (any staff can read)."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.company_id == current.company_id, User.is_active.is_(True))
        .order_by(User.first_name.asc())
    )
    members: list[MemberOut] = []
    for u in result.scalars().all():
        role_name = u.role.name if u.role else "employee"
        if role_name == "client":
            continue
        full_name = f"{u.first_name} {u.last_name or ''}".strip()
        members.append(MemberOut(id=u.id, name=full_name, email=u.email, role=role_name))
    return members


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    groups_result = await db.execute(
        select(Group).where(Group.company_id == current.company_id).order_by(Group.created_at.desc())
    )
    groups = groups_result.scalars().all()
    if not groups:
        return []

    group_ids = [g.id for g in groups]
    members_result = await db.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id.in_(group_ids))
        .order_by(User.first_name.asc())
    )
    grouped: dict[UUID, list[GroupMemberOut]] = {g.id: [] for g in groups}
    for gm, user in members_result.all():
        grouped[gm.group_id].append(
            GroupMemberOut(
                id=user.id,
                name=f"{user.first_name} {user.last_name or ''}".strip(),
                email=user.email,
                status="Active" if user.is_active and user.is_verified else "Pending",
            )
        )

    output: list[GroupOut] = []
    for g in groups:
        members = grouped.get(g.id, [])
        output.append(
            GroupOut(
                id=g.id,
                name=g.name,
                members_count=len(members),
                users_count=len(members),
                roles_count=0,
                members=members,
            )
        )
    return output


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreateRequest,
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")

    existing = await db.execute(
        select(Group).where(Group.company_id == current.company_id, Group.name == name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Group with this name already exists")

    group = Group(company_id=current.company_id, name=name, created_by_id=current.id)
    db.add(group)
    await db.flush()

    members: list[GroupMemberOut] = []
    if body.member_ids:
        users_result = await db.execute(
            select(User).where(User.company_id == current.company_id, User.id.in_(body.member_ids))
        )
        users = users_result.scalars().all()
        for user in users:
            db.add(GroupMember(group_id=group.id, user_id=user.id))
            members.append(
                GroupMemberOut(
                    id=user.id,
                    name=f"{user.first_name} {user.last_name or ''}".strip(),
                    email=user.email,
                    status="Active" if user.is_active and user.is_verified else "Pending",
                )
            )

    return GroupOut(
        id=group.id,
        name=group.name,
        members_count=len(members),
        users_count=len(members),
        roles_count=0,
        members=members,
    )


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
    username = await unique_username(db, username_from_email(body.email))

    user = User(
        company_id=current.company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        username=username,
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


@router.post("/invite", response_model=StaffInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_staff(
    body: StaffInviteRequest,
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
    company = await db.get(Company, current.company_id)
    username = await unique_username(db, username_from_email(body.email))

    user = User(
        company_id=current.company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        username=username,
        email=body.email,
        password_hash=hash_password(generate_reset_token()[:32]),
        phone=body.phone,
        role_id=role.id,
        is_active=True,
        is_verified=False,
        invited_by_id=current.user.id,
    )
    db.add(user)
    await db.flush()

    invite_token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(invite_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    await db.flush()

    workspace = company.company_name if company else "AgencyFlow"
    invite_link = (
        f"{settings.frontend_url}/join?token={invite_token}"
        f"&email={body.email}"
    )
    decline_link = invite_link
    inviter_name = f"{current.user.first_name} {current.user.last_name or ''}".strip()
    email_ok, email_err = await send_staff_invite_email(
        body.email,
        body.first_name,
        workspace,
        invite_link,
        inviter_name=inviter_name,
        inviter_email=current.user.email,
        decline_link=decline_link,
    )

    expose_token = invite_token if (not email_ok or settings.debug) else None
    if email_ok:
        message = "Invitation email sent"
    elif settings.debug or not settings.email_enabled:
        message = "Invite created — share the link below (email could not be sent)"
    else:
        message = "User invited but email could not be sent — share the invite link manually"

    return StaffInviteResponse(
        id=user.id,
        email=body.email,
        invite_token=expose_token,
        email_sent=email_ok,
        email_error=email_err,
        message=message,
    )


@router.post("/{user_id}/resend-invite", response_model=StaffInviteResponse)
async def resend_invite(
    user_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id, User.company_id == current.company_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_verified:
        raise HTTPException(status_code=400, detail="User has already accepted the invite")
    if user.role and user.role.name == "owner":
        raise HTTPException(status_code=400, detail="Cannot resend invite for owner")

    company = await db.get(Company, current.company_id)
    workspace = company.company_name if company else "AgencyFlow"

    invite_token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(invite_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    await db.flush()

    invite_link = f"{settings.frontend_url}/join?token={invite_token}&email={user.email}"
    inviter_name = f"{current.user.first_name} {current.user.last_name or ''}".strip()
    email_ok, email_err = await send_staff_invite_email(
        user.email,
        user.first_name,
        workspace,
        invite_link,
        inviter_name=inviter_name,
        inviter_email=current.user.email,
        decline_link=invite_link,
    )

    expose_token = invite_token if (not email_ok or settings.debug) else None
    if email_ok:
        message = "Invitation email resent"
    else:
        message = "New invite link created — share it manually (email could not be sent)"

    return StaffInviteResponse(
        id=user.id,
        email=user.email,
        invite_token=expose_token,
        email_sent=email_ok,
        email_error=email_err,
        message=message,
    )


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
