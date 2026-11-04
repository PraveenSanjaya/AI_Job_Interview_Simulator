"""Authentication endpoints."""

import hashlib

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, ClientIpDep, CurrentUserDep, RateLimiterDep
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> UserResponse:
    limiter.hit(f"register:ip:{ip}")
    user = await service.register(
        email=body.email, password=body.password, full_name=body.full_name
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> TokenResponse:
    # Throttle per client address and per target account (digest keeps raw emails
    # out of limiter state) to slow both credential stuffing and targeted guessing.
    limiter.hit(f"login:ip:{ip}")
    limiter.hit(f"login:email:{hashlib.sha256(body.email.encode()).hexdigest()}")
    return await service.login(email=body.email, password=body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> TokenResponse:
    """Exchange a refresh token for a new pair. The presented token is single-use."""
    limiter.hit(f"refresh:ip:{ip}")
    return await service.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> None:
    """Revoke the session for this refresh token. Always 204 (idempotent)."""
    limiter.hit(f"logout:ip:{ip}")
    await service.logout(body.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDep) -> UserResponse:
    """The authenticated user's account."""
    return UserResponse.model_validate(user)
