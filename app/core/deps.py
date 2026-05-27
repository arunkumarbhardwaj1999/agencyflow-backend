from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import decode_token, token_subject_uuid
from app.db.session import get_db
from app.integrations.supabase_auth import get_supabase_user_id
from app.models.role import Role
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)
settings = get_settings()

ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    "owner": {
        "view_analytics": True,
        "manage_staff": True,
        "manage_leads": True,
        "manage_projects": True,
        "manage_tasks": True,
        "update_assigned_tasks": True,
        "manage_invoices": True,
        "view_portal": True,
    },
    "manager": {
        "view_analytics": False,
        "manage_staff": False,
        "manage_leads": True,
        "manage_projects": True,
        "manage_tasks": True,
        "update_assigned_tasks": True,
        "manage_invoices": True,
        "view_portal": True,
    },
    "employee": {
        "view_analytics": False,
        "manage_staff": False,
        "manage_leads": False,
        "manage_projects": False,
        "manage_tasks": False,
        "update_assigned_tasks": True,
        "manage_invoices": False,
        "view_portal": True,
    },
    "client": {
        "view_analytics": False,
        "manage_staff": False,
        "manage_leads": False,
        "manage_projects": False,
        "manage_tasks": False,
        "update_assigned_tasks": False,
        "manage_invoices": False,
        "view_portal": True,
    },
}


@dataclass
class CurrentUser:
    user: User
    role_name: str

    @property
    def id(self) -> UUID:
        return self.user.id

    @property
    def company_id(self) -> UUID | None:
        return self.user.company_id

    def can(self, permission: str) -> bool:
        perms = ROLE_PERMISSIONS.get(self.role_name, {})
        return perms.get(permission, False)


async def _user_from_supabase_token(token: str, db: AsyncSession) -> CurrentUser | None:
    if not settings.supabase_jwt_secret:
        return None
    try:
        supabase_uid = get_supabase_user_id(token)
    except (JWTError, ValueError):
        return None

    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.supabase_user_id == supabase_uid, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    role_name = user.role.name if user.role else "employee"
    return CurrentUser(user=user, role_name=role_name)


async def _user_from_legacy_token(token: str, db: AsyncSession) -> CurrentUser | None:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = token_subject_uuid(payload)
    except (JWTError, ValueError):
        return None

    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    role_name = user.role.name if user.role else "employee"
    return CurrentUser(user=user, role_name=role_name)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials
    current = await _user_from_supabase_token(token, db)
    if not current:
        current = await _user_from_legacy_token(token, db)
    if not current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return current


def require_permission(permission: str):
    async def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.can(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current

    return checker


def require_company(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not current.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace associated")
    return current
