"""Session cookies and their CSRF protection.

The refresh token lives only in an ``HttpOnly`` cookie, so page JavaScript can never read
it. Because browsers attach cookies automatically, the endpoints that accept the cookie
(``/auth/refresh`` and ``/auth/logout``) are protected against cross-site request forgery
in layers:

1. ``SameSite=Strict``: the browser does not send the cookie on cross-site requests.
2. Origin check: the request must come from an allowed front-end origin (``Origin``, or
   ``Referer`` when ``Origin`` is absent); a request with neither is refused.
3. Double-submit token: a second, script-readable cookie (``csrf_token``) must be echoed
   in the ``X-CSRF-Token`` header. A foreign site can neither read that cookie nor set
   that header.

The browser-visible CSRF cookie also tells the front end that a session cookie exists,
without exposing the session itself.
"""

import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.core.config import Settings
from app.core.exceptions import ForbiddenError

CSRF_HEADER = "X-CSRF-Token"
AUTH_COOKIE_PATH = "/api/v1/auth"


def allowed_origins(settings: Settings) -> set[str]:
    """The browser origins allowed to use the cookie (same list CORS uses)."""
    return {
        origin.rstrip("/")
        for origin in [settings.frontend_url, *settings.cors_allowed_origins]
        if origin
    }


def set_session_cookies(response: Response, settings: Settings, refresh_token: str) -> None:
    max_age = settings.jwt_refresh_token_expire_days * 24 * 3600
    secure = settings.refresh_cookie_secure
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=max_age,
        path=AUTH_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        secrets.token_urlsafe(32),
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,  # must be readable by the front end to be echoed in the header
        samesite="strict",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    secure = settings.refresh_cookie_secure
    response.delete_cookie(
        settings.refresh_cookie_name,
        path=AUTH_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.csrf_cookie_name, path="/", secure=secure, httponly=False, samesite="strict"
    )


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def verify_cookie_request(request: Request, settings: Settings) -> None:
    """Refuse a cookie-authenticated request that is not clearly from our own front end."""
    origin = _origin_of(request.headers.get("origin")) or _origin_of(request.headers.get("referer"))
    allowed = {o.lower() for o in allowed_origins(settings)}
    if origin is None or origin not in allowed:
        raise ForbiddenError("Request origin is not allowed", code="csrf_failed")
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise ForbiddenError("Missing or invalid CSRF token", code="csrf_failed")
