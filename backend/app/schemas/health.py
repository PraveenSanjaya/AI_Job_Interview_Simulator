"""Response models for health endpoints."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "not_configured", "unchecked", "error"]


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyCheck(BaseModel):
    status: CheckStatus
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyCheck]
