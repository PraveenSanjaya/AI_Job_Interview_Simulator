"""Response models for health endpoints."""

from typing import Literal

from pydantic import BaseModel

# "degraded": configured but unreachable, while the application keeps working without it.
CheckStatus = Literal["ok", "not_configured", "unchecked", "degraded", "error"]


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyCheck(BaseModel):
    status: CheckStatus
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyCheck]
