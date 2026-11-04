"""Shared FastAPI dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.rate_limit import RateLimiter
from app.core.tokens import decode_access_token
from app.db.session import get_session
from app.models import User
from app.models.enums import UserRole
from app.repositories.users import UserRepository
from app.services.auth import AuthService

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    """Direct peer address. Behind a reverse proxy, configure the server's trusted
    proxy headers (e.g. uvicorn ``--proxy-headers --forwarded-allow-ips``) so this
    reflects the real client rather than the proxy."""
    return request.client.host if request.client else "unknown"


ClientIpDep = Annotated[str, Depends(client_ip)]


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    """Authenticate the request from its ``Authorization: Bearer`` access token."""
    if credentials is None:
        raise UnauthorizedError("Not authenticated", code="not_authenticated")
    claims = decode_access_token(credentials.credentials, settings)
    user = await UserRepository(session).get_by_id(claims.user_id)
    # The same error for "deleted" and "disabled" avoids confirming account state.
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid access token", code="invalid_token")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed: UserRole) -> Callable[[User], User]:
    """Dependency factory restricting a route to users holding one of ``allowed``."""

    def dependency(user: CurrentUserDep) -> User:
        if user.role not in allowed:
            raise ForbiddenError("You do not have permission to perform this action")
        return user

    return dependency
