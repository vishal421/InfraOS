from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, ROLE_OPERATOR, User

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    """Lightweight, request-scoped view of the authenticated principal —
    avoids re-fetching the full User row on every dependency resolution
    while still giving handlers id/username/role."""

    def __init__(self, id: str, username: str, role: str):
        self.id = id
        self.username = username
        self.role = role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}") from exc

    return CurrentUser(id=payload["sub"], username=payload["username"], role=payload["role"])


def require_role(*allowed_roles: str):
    """Usage: Depends(require_role(ROLE_ADMIN)) or Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))"""

    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role}' is not permitted to perform this action (requires one of {allowed_roles})",
            )
        return user

    return dependency


# Convenience shorthands used across routers
require_operator = require_role(ROLE_OPERATOR, ROLE_ADMIN)
require_admin = require_role(ROLE_ADMIN)
