"""Rate limiting.

* ``InMemoryRateLimiter`` is a sliding-window limiter that lives inside one process. It
  protects a single instance (development, one worker) but is NOT shared between workers
  or hosts.
* ``RedisRateLimiter`` keeps the counters in Redis so every worker and host shares them.
  It never makes the application depend on Redis: if Redis cannot be reached the request
  is counted by an in-process fallback limiter instead (and a warning is logged), so
  rate limiting degrades to per-process rather than disappearing or blocking everyone.

Redis keys are a SHA-256 digest of the logical key, so addresses and user ids never
appear in Redis.
"""

import hashlib
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from app.core.exceptions import TooManyRequestsError

logger = logging.getLogger(__name__)
_MAX_TRACKED_KEYS = 10_000

# Atomic fixed window: count the hit and make sure the key always expires, even if a
# previous caller died between INCR and PEXPIRE. Returns {count, milliseconds_left}.
_REDIS_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


class RateLimiter(Protocol):
    async def hit(self, key: str) -> None:
        """Record an attempt for ``key``; raise ``TooManyRequestsError`` if over the limit."""
        ...


class RedisLike(Protocol):
    """The part of ``redis.asyncio.Redis`` this module uses."""

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...

    async def ping(self) -> Any: ...


class NoopRateLimiter:
    """Used when rate limiting is disabled by configuration."""

    async def hit(self, key: str) -> None:
        return None


class InMemoryRateLimiter:
    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    async def hit(self, key: str) -> None:
        now = self._clock()
        if len(self._events) >= _MAX_TRACKED_KEYS:
            self._evict_expired(now)
        events = self._events.setdefault(key, deque())
        while events and now - events[0] >= self._window:
            events.popleft()
        if len(events) >= self._max_attempts:
            retry_after = math.ceil(self._window - (now - events[0]))
            raise TooManyRequestsError(retry_after)
        events.append(now)

    def _evict_expired(self, now: float) -> None:
        for key in [k for k, v in self._events.items() if not v or now - v[-1] >= self._window]:
            del self._events[key]


class RedisRateLimiter:
    """Fixed-window limiter shared through Redis, with an in-process fallback."""

    def __init__(
        self,
        client: RedisLike,
        max_attempts: int,
        window_seconds: int,
        *,
        fallback: RateLimiter,
        prefix: str = "ratelimit:",
        clock: Callable[[], float] = time.monotonic,
        warn_every_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self._window_ms = window_seconds * 1000
        self._fallback = fallback
        self._prefix = prefix
        self._clock = clock
        self._warn_every = warn_every_seconds
        self._last_warning: float | None = None

    async def hit(self, key: str) -> None:
        redis_key = self._prefix + hashlib.sha256(key.encode()).hexdigest()
        try:
            count, ttl_ms = await self._client.eval(
                _REDIS_HIT_SCRIPT, 1, redis_key, self._window_ms
            )
        except Exception:
            self._warn_unavailable()
            await self._fallback.hit(key)
            return
        if int(count) > self._max_attempts:
            raise TooManyRequestsError(max(1, math.ceil(int(ttl_ms) / 1000)))

    def _warn_unavailable(self) -> None:
        now = self._clock()
        if self._last_warning is None or now - self._last_warning >= self._warn_every:
            self._last_warning = now
            logger.warning(
                "Redis rate limiter unavailable; counting in this process instead",
                exc_info=True,
            )
