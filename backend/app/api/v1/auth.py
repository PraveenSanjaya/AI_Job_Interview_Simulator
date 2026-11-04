"""Authentication endpoints."""

import hashlib

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, ClientIpDep, RateLimiterDep
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

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
