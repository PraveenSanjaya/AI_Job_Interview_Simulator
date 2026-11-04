"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter
from app.db.session import get_session
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
