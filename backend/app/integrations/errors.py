"""Errors for public-source integrations (GitHub, portfolio).

Messages are safe to show to users and never include fetched content.
"""

from fastapi import status

from app.core.exceptions import AppError


class InvalidGitHubUsernameError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_github_username"


class GitHubUserNotFoundError(AppError):
    """No such public user (nonexistent, deleted, suspended or renamed)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "github_user_not_found"


class GitHubNotAUserError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "github_not_a_user"


class GitHubRateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "github_rate_limited"

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        headers = {"Retry-After": str(max(1, retry_after_seconds))} if retry_after_seconds else None
        super().__init__("GitHub's API rate limit was reached; try again later", headers=headers)


class GitHubUnavailableError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "github_unavailable"


class PortfolioUrlRejectedError(AppError):
    """The URL is not an acceptable public web address (scheme, host, port or network)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "portfolio_url_rejected"


class PortfolioFetchError(AppError):
    """The page could not be retrieved or is not usable (timeout, size, type, status)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "portfolio_fetch_failed"


class SourceNotConnectedError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "source_not_connected"
