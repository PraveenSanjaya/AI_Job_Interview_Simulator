"""Readiness checks, kept separate from HTTP routing.

A dependency is only reported ``ok`` after a real connectivity probe succeeds.
Database and Redis probes arrive with their integration phases; until then a
configured URL is reported ``unchecked`` and a missing URL ``not_configured``.
"""

from app.core.config import Settings
from app.schemas.health import DependencyCheck, ReadinessResponse


def _check_configured_only(name: str, url: str | None) -> DependencyCheck:
    if url is None:
        return DependencyCheck(status="not_configured")
    return DependencyCheck(
        status="unchecked",
        detail=f"{name} is configured but no connectivity probe is implemented yet",
    )


def run_readiness_checks(settings: Settings) -> ReadinessResponse:
    checks = {
        "database": _check_configured_only("database", settings.database_url),
        "redis": _check_configured_only("redis", settings.redis_url),
    }
    # Nothing is mandatory yet; only an actively failing dependency blocks readiness.
    failed = any(check.status == "error" for check in checks.values())
    return ReadinessResponse(status="not_ready" if failed else "ready", checks=checks)
