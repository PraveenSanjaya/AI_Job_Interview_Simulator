"""Liveness and readiness endpoints (unversioned, for orchestrators)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.schemas.health import LivenessResponse, ReadinessResponse
from app.services.health import run_readiness_checks

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Process is up and able to serve requests."""
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse)
async def ready(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> ReadinessResponse:
    """Dependencies required to serve traffic are available."""
    result = run_readiness_checks(settings)
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
