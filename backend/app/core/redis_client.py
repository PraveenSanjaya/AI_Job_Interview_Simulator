"""Optional Redis connection.

Redis is never required. ``create_redis_client`` returns ``None`` when no URL is
configured or the ``redis`` package is not installed, and the application then keeps
working with in-process rate limiting.
"""

import logging

from app.core.rate_limit import RedisLike

logger = logging.getLogger(__name__)
REDIS_TIMEOUT_SECONDS = 1.0


def create_redis_client(url: str | None) -> RedisLike | None:
    """Build a lazy client (no connection is made here). The URL is never logged."""
    if url is None:
        return None
    try:
        from redis.asyncio import Redis
    except ImportError:
        logger.warning(
            "REDIS_URL is set but the 'redis' package is not installed; "
            "continuing without Redis (rate limiting stays in-process)"
        )
        return None
    client: RedisLike = Redis.from_url(
        url,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )
    return client


async def close_redis_client(client: object | None) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()
