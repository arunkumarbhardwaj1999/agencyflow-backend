from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token, token_subject_uuid
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = token_subject_uuid(payload)
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None

    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    role_name = user.role.name if user.role else "employee"
    return CurrentUser(user=user, role_name=role_name)


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
