"""Readiness checks, kept separate from HTTP routing.

A dependency is only reported ``ok`` after a real connectivity probe succeeds.
The database is probed with ``SELECT 1`` and Redis with ``PING``. Redis is optional
(rate limiting falls back to the process), so an unreachable Redis is ``degraded`` and
does not make the service unready, while an unreachable database does. A configured
Redis URL with no client (package not installed) is ``unchecked``.
Connection error details are logged, never returned (they may contain hosts).
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.rate_limit import RedisLike
from app.schemas.health import DependencyCheck, ReadinessResponse

logger = logging.getLogger(__name__)
DB_PROBE_TIMEOUT_SECONDS = 3.0
REDIS_PROBE_TIMEOUT_SECONDS = 2.0


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


async def check_redis(redis_url: str | None, client: RedisLike | None) -> DependencyCheck:
    if redis_url is None:
        return DependencyCheck(status="not_configured")
    if client is None:
        return DependencyCheck(
            status="unchecked",
            detail="redis is configured but no client is available (is the package installed?)",
        )
    try:
        async with asyncio.timeout(REDIS_PROBE_TIMEOUT_SECONDS):
            await client.ping()
    except Exception:
        logger.warning("Redis readiness probe failed", exc_info=True)
        return DependencyCheck(
            status="degraded",
            detail="redis unreachable; rate limiting is per process until it returns",
        )
    return DependencyCheck(status="ok")


async def run_readiness_checks(
    settings: Settings, engine: AsyncEngine | None, redis: RedisLike | None = None
) -> ReadinessResponse:
    checks = {
        "database": await check_database(engine),
        "redis": await check_redis(settings.redis_url, redis),
    }
    # Only an actively failing dependency blocks readiness.
    failed = any(check.status == "error" for check in checks.values())
    return ReadinessResponse(status="not_ready" if failed else "ready", checks=checks)
