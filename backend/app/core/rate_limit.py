"""Rate limiting.

``InMemoryRateLimiter`` is a sliding-window limiter that lives inside one process.
It protects a single instance (development, one worker) but is NOT shared between
workers or hosts, so it is not a substitute for a distributed limiter. The
``RateLimiter`` protocol exists so a Redis-backed implementation can replace it
once Redis is integrated; until then nothing here talks to Redis.
"""

import math
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from app.core.exceptions import TooManyRequestsError

_MAX_TRACKED_KEYS = 10_000


class RateLimiter(Protocol):
    def hit(self, key: str) -> None:
        """Record an attempt for ``key``; raise ``TooManyRequestsError`` if over the limit."""
        ...


class NoopRateLimiter:
    """Used when rate limiting is disabled by configuration."""

    def hit(self, key: str) -> None:
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

    def hit(self, key: str) -> None:
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
