"""Domain exceptions and centralized exception handlers.

All error responses share one shape::

    {"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}

Internal error details (stack traces, exception text) are logged, never returned.
"""

import logging
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected, client-facing application errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "app_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"

    def __init__(self, message: str = "Not authenticated", *, code: str | None = None) -> None:
        super().__init__(message, code=code, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request.scope.get("request_id")
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    headers = dict(extra_headers or {})
    if request_id:
        headers["X-Request-ID"] = request_id
    return JSONResponse({"error": body}, status_code=status_code, headers=headers or None)


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    return _error_response(
        request, exc.status_code, exc.code, exc.message, extra_headers=exc.headers
    )


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    return _error_response(request, exc.status_code, "http_error", str(exc.detail))


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    details = [
        {"location": [str(part) for part in err["loc"]], "message": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return _error_response(
        request,
        422,
        "validation_error",
        "Request validation failed",
        details,
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception", exc_info=exc)
    return _error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
