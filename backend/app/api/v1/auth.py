"""Authentication endpoints."""

import contextlib
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    AuthServiceDep,
    ClientIpDep,
    CurrentUserDep,
    LoginFailureLimiterDep,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
)
from app.core.config import Settings
from app.core.cookies import clear_session_cookies, set_session_cookies, verify_cookie_request
from app.core.exceptions import TooManyRequestsError, UnauthorizedError, error_response
from app.schemas.auth import (
    AccessTokenResponse,
    AccountDeletionResult,
    DeleteAccountRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationAccepted,
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


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    failures: LoginFailureLimiterDep,
    ip: ClientIpDep,
) -> AccessTokenResponse:
    """Sign in. The access token is returned in the body; the refresh token is set as an
    ``HttpOnly`` cookie and never appears in the response body.

    Throttling is designed so that nobody can lock someone else out:

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
        issued = await service.login(email=body.email, password=body.password)
    except UnauthorizedError:
        # If a concurrent request pushed the count over the limit, the next attempt is
        # refused by peek(); this request still reports the real 401.
        with contextlib.suppress(TooManyRequestsError):
            await failures.hit(f"login-failures:{account}")
        raise
    set_session_cookies(response, settings, issued.refresh_token)
    return issued.public()


def _session_token(
    request: Request, body: RefreshRequest | None, settings: Settings
) -> tuple[str | None, bool]:
    """The refresh token to use and whether it came from the cookie (needs CSRF checks).

    A token in the body is the legacy path: it is itself the secret and is not sent
    automatically by browsers, so it is not CSRF-prone.
    """
    if body is not None and body.refresh_token and settings.allow_legacy_refresh_body:
        return body.refresh_token, False
    cookie = request.cookies.get(settings.refresh_cookie_name)
    return (cookie or None), True


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
    body: RefreshRequest | None = None,
) -> AccessTokenResponse | JSONResponse:
    """Exchange the refresh cookie for a new access token and a rotated cookie.

    The presented token is single-use. Presenting an already-used token revokes the whole
    session. A refresh that fails clears the session cookies, so a dead credential is not
    retried. Requests that rely on the cookie must come from an allowed origin and carry
    the ``X-CSRF-Token`` header (``403 csrf_failed`` otherwise).
    """
    await limiter.hit(f"refresh:ip:{ip}")
    token, from_cookie = _session_token(request, body, settings)
    if from_cookie:
        verify_cookie_request(request, settings)
    try:
        if token is None:
            raise UnauthorizedError(
                "Invalid or expired refresh token", code="invalid_refresh_token"
            )
        issued = await service.refresh(token)
    except UnauthorizedError as error:
        failed = error_response(request, error.status_code, error.code, error.message)
        clear_session_cookies(failed, settings)
        return failed
    set_session_cookies(response, settings, issued.refresh_token)
    return issued.public()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    ip: ClientIpDep,
    body: LogoutRequest | None = None,
) -> None:
    """End this login session and clear its cookies. Always 204 (idempotent).

    Cookie-based requests need the same origin and CSRF token as refresh. Access tokens of
    the session stop working immediately.
    """
    await limiter.hit(f"logout:ip:{ip}")
    token, from_cookie = _session_token(request, body, settings)
    if token is not None:
        if from_cookie:
            verify_cookie_request(request, settings)
        await service.logout(token)
    clear_session_cookies(response, settings)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDep) -> UserResponse:
    """The authenticated user's account."""
    return UserResponse.model_validate(user)


@router.post("/delete-account", response_model=AccountDeletionResult)
async def delete_account(
    body: DeleteAccountRequest,
    response: Response,
    settings: SettingsDep,
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
    clear_session_cookies(response, settings)  # the session no longer exists
    return AccountDeletionResult(stored_files_removed=files_removed)
