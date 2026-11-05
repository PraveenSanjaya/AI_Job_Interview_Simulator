"""Authentication endpoints."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import AuthServiceDep, ClientIpDep, CurrentUserDep, RateLimiterDep, SessionDep
from app.schemas.auth import (
    AccountDeletionResult,
    DeleteAccountRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationAccepted,
    TokenResponse,
    UserResponse,
)
from app.services.account import AccountService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_account_service(request: Request, session: SessionDep) -> AccountService:
    return AccountService(session, request.app.state.storage)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


@router.post("/register", response_model=RegistrationAccepted, status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> RegistrationAccepted:
    """Always answers 202 with the same body, whether or not the email was taken."""
    await limiter.hit(f"register:ip:{ip}")
    await service.register(email=body.email, password=body.password, full_name=body.full_name)
    return RegistrationAccepted()


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> TokenResponse:
    # Throttle per client address and per target account (digest keeps raw emails
    # out of limiter state) to slow both credential stuffing and targeted guessing.
    await limiter.hit(f"login:ip:{ip}")
    await limiter.hit(f"login:email:{hashlib.sha256(body.email.encode()).hexdigest()}")
    return await service.login(email=body.email, password=body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> TokenResponse:
    """Exchange a refresh token for a new pair. The presented token is single-use."""
    await limiter.hit(f"refresh:ip:{ip}")
    return await service.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
) -> None:
    """Revoke the session for this refresh token. Always 204 (idempotent)."""
    await limiter.hit(f"logout:ip:{ip}")
    await service.logout(body.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDep) -> UserResponse:
    """The authenticated user's account."""
    return UserResponse.model_validate(user)


@router.post("/delete-account", response_model=AccountDeletionResult)
async def delete_account(
    body: DeleteAccountRequest,
    user: CurrentUserDep,
    service: AccountServiceDep,
    limiter: RateLimiterDep,
) -> AccountDeletionResult:
    """Permanently delete your account and all of your data. Requires your password.

    * 403 ``incorrect_password``: nothing was deleted.

    Deletes the profile, resumes (and the stored files), connections, jobs, matches,
    interviews and reports, and ends every session. This cannot be undone.
    """
    await limiter.hit(f"account-delete:user:{user.id}")
    files_removed = await service.delete_account(user, body.password)
    return AccountDeletionResult(stored_files_removed=files_removed)
