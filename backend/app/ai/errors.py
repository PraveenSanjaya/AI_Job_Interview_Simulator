"""Errors raised by AI providers and the analysis pipeline.

They are ``AppError`` subclasses so they map directly to clean HTTP responses. Their
messages never include prompts, resume text or provider response bodies.
"""

from fastapi import status

from app.core.exceptions import AppError


class AIUnavailableError(AppError):
    """No usable provider: not configured, or credentials were rejected."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "ai_unavailable"


class AITimeoutError(AppError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "ai_timeout"


class AIRateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "ai_rate_limited"

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        headers = {"Retry-After": str(max(1, retry_after_seconds))} if retry_after_seconds else None
        super().__init__(
            "The AI provider is rate limiting requests; try again later", headers=headers
        )


class AIProviderError(AppError):
    """The provider failed (network error, 5xx, unexpected status)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "ai_provider_error"


class AIResponseError(AppError):
    """The provider answered, but not with usable, schema-valid JSON."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "invalid_ai_response"


class AIConsentRequiredError(AppError):
    """Sending the resume to an external provider needs the user's explicit consent."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "ai_consent_required"
