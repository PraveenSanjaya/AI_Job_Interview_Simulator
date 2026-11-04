"""Errors for job descriptions. Messages are safe to show and never echo job text."""

from fastapi import status

from app.core.exceptions import AppError


class JobNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "job_not_found"

    def __init__(self) -> None:
        super().__init__("Job not found")


class JobAnalysisNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "analysis_not_found"

    def __init__(self) -> None:
        super().__init__("This job has no analysis yet")


class JobMatchNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "match_not_found"

    def __init__(self) -> None:
        super().__init__("Match not found")


class InvalidJobDescriptionError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_job_description"


class JobUrlRejectedError(AppError):
    """The job link is not an acceptable public web address."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "job_url_rejected"


class JobPlatformNotSupportedError(AppError):
    """Sites that forbid automated access or require a login are never fetched."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "job_platform_not_supported"


class JobFetchError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "job_fetch_failed"
