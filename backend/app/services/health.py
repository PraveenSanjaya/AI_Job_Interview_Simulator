"""Readiness checks, kept separate from HTTP routing.

A dependency is only reported ``ok`` after a real connectivity probe succeeds.
The database is probed with ``SELECT 1``. Redis has no client yet, so a
configured URL is reported ``unchecked`` and a missing URL ``not_configured``.
Connection error details are logged, never returned (they may contain hosts).
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.schemas.health import DependencyCheck, ReadinessResponse

logger = logging.getLogger(__name__)
DB_PROBE_TIMEOUT_SECONDS = 3.0


async def check_database(engine: AsyncEngine | None) -> DependencyCheck:
    if engine is None:
        return DependencyCheck(status="not_configured")
    try:
        async with asyncio.timeout(DB_PROBE_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Database readiness probe failed", exc_info=True)
        return DependencyCheck(status="error", detail="database connection failed")
    return DependencyCheck(status="ok")


def check_redis(redis_url: str | None) -> DependencyCheck:
    if redis_url is None:
        return DependencyCheck(status="not_configured")
    return DependencyCheck(
        status="unchecked",
        detail="redis is configured but no connectivity probe is implemented yet",
    )


async def run_readiness_checks(settings: Settings, engine: AsyncEngine | None) -> ReadinessResponse:
    checks = {
        "database": await check_database(engine),
        "redis": check_redis(settings.redis_url),
    }
    # Only an actively failing dependency blocks readiness.
    failed = any(check.status == "error" for check in checks.values())
    return ReadinessResponse(status="not_ready" if failed else "ready", checks=checks)
