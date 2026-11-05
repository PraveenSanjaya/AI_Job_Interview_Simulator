"""Authentication endpoints."""

import contextlib
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    AuthServiceDep,
    ClientIpDep,
    CurrentUserDep,
    LoginFailureLimiterDep,
    RateLimiterDep,
    SessionDep,
)
from app.core.exceptions import TooManyRequestsError, UnauthorizedError
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
    failures: LoginFailureLimiterDep,
    ip: ClientIpDep,
) -> TokenResponse:
    """Sign in. Throttling is designed so that nobody can lock someone else out:

    * every attempt from one client address is limited (``login:ip``);
    * every attempt for one account *from one client address* is limited, so an attacker
      hammering an account only exhausts their own budget for it;
    * failed attempts for one account across all addresses are limited by a much higher
      ceiling, which bounds guessing spread over many addresses.

    The e-mail is hashed so raw addresses never reach limiter state.
    """
    account = hashlib.sha256(body.email.encode()).hexdigest()
    await limiter.hit(f"login:ip:{ip}")
    await limiter.hit(f"login:account-ip:{account}:{ip}")
    await failures.peek(f"login-failures:{account}")
    try:
        return await service.login(email=body.email, password=body.password)
    except UnauthorizedError:
        # If a concurrent request pushed the count over the limit, the next attempt is
        # refused by peek(); this request still reports the real 401.
        with contextlib.suppress(TooManyRequestsError):
            await failures.hit(f"login-failures:{account}")
        raise


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
