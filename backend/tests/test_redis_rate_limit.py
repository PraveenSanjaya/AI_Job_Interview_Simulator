"""Redis-backed rate limiting and readiness, tested against an in-memory fake.

IMPORTANT: no real Redis server was available when these tests were written. The fake
below emulates the semantics of the Lua script (INCR / PEXPIRE / PTTL) so the limiter's own
logic (key hashing, window arithmetic, error handling, fallback) is verified, but the Lua
script itself and the real ``redis`` client have NOT been run against a real server.
"""

import logging
import sys
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.core.redis_client import create_redis_client
from app.services.health import check_redis
from tests.helpers import login, register

pytestmark = pytest.mark.anyio


class FakeRedis:
    """Emulates the bits of Redis the limiter's script relies on, with a fake clock."""

    def __init__(self) -> None:
        self.now_ms = 0
        self.counters: dict[str, int] = {}
        self.expires_at: dict[str, int] = {}
        self.eval_calls: list[tuple[Any, ...]] = []
        self.fail_with: Exception | None = None

    def _expire_due(self) -> None:
        for key in [k for k, at in self.expires_at.items() if at <= self.now_ms]:
            self.counters.pop(key, None)
            del self.expires_at[key]

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        self.eval_calls.append((script, numkeys, *keys_and_args))
        if self.fail_with is not None:
            raise self.fail_with
        assert numkeys == 1
        key = keys_and_args[0]
        self._expire_due()
        if "INCR" not in script:  # the read-only peek script: {count, ttl} without counting
            left = self.expires_at[key] - self.now_ms if key in self.expires_at else -2
            return [self.counters.get(key, 0), left]
        window_ms = int(keys_and_args[1])
        self.counters[key] = self.counters.get(key, 0) + 1
        if key not in self.expires_at:
            self.expires_at[key] = self.now_ms + window_ms
        return [self.counters[key], self.expires_at[key] - self.now_ms]

    async def ping(self) -> bool:
        if self.fail_with is not None:
            raise self.fail_with
        return True


def limiter_for(
    redis: FakeRedis, attempts: int = 3, window: int = 60
) -> tuple[RedisRateLimiter, InMemoryRateLimiter]:
    fallback = InMemoryRateLimiter(attempts, window)
    return RedisRateLimiter(redis, attempts, window, fallback=fallback), fallback


async def test_allows_up_to_the_limit_then_blocks_with_the_remaining_window() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis)
    for _ in range(3):
        await limiter.hit("login:ip:1.2.3.4")
    redis.now_ms += 10_000
    with pytest.raises(TooManyRequestsError) as error:
        await limiter.hit("login:ip:1.2.3.4")
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "50"}


async def test_the_window_resets_after_it_expires() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis, attempts=1)
    await limiter.hit("k")
    with pytest.raises(TooManyRequestsError):
        await limiter.hit("k")
    redis.now_ms += 60_000
    await limiter.hit("k")


async def test_keys_are_independent() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis, attempts=1)
    await limiter.hit("a")
    await limiter.hit("b")
    with pytest.raises(TooManyRequestsError):
        await limiter.hit("a")


async def test_two_workers_share_one_budget() -> None:
    """The point of Redis: separate limiter instances (processes) see the same counts."""
    redis = FakeRedis()
    worker_1, _ = limiter_for(redis, attempts=2)
    worker_2, _ = limiter_for(redis, attempts=2)
    await worker_1.hit("login:email:x")
    await worker_2.hit("login:email:x")
    with pytest.raises(TooManyRequestsError):
        await worker_1.hit("login:email:x")
    with pytest.raises(TooManyRequestsError):
        await worker_2.hit("login:email:x")


async def test_redis_keys_never_contain_addresses_or_user_ids() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis)
    await limiter.hit("login:ip:203.0.113.9")
    await limiter.hit("integration:user:7b1f0c1e-0000-4000-8000-000000000000")
    for key in redis.counters:
        assert key.startswith("ratelimit:")
        assert "203.0.113.9" not in key and "7b1f0c1e" not in key
        assert len(key) == len("ratelimit:") + 64


async def test_the_script_sets_the_expiry_atomically_with_the_count() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis, window=90)
    await limiter.hit("k")
    script, numkeys, _key, window_ms = redis.eval_calls[0]
    assert numkeys == 1 and window_ms == 90_000
    assert "INCR" in script and "PEXPIRE" in script and "PTTL" in script


async def test_an_unreachable_redis_falls_back_to_the_in_process_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedis()
    redis.fail_with = ConnectionError("redis://user:secret@host is down")
    limiter, _ = limiter_for(redis, attempts=2)
    with caplog.at_level(logging.WARNING):
        await limiter.hit("k")
        await limiter.hit("k")
        with pytest.raises(TooManyRequestsError):  # still limited, now per process
            await limiter.hit("k")
    assert sum("unavailable" in r.getMessage() for r in caplog.records) == 1  # not one per call


async def test_the_limiter_recovers_when_redis_returns() -> None:
    redis = FakeRedis()
    limiter, fallback = limiter_for(redis, attempts=1)
    redis.fail_with = ConnectionError("down")
    await limiter.hit("k")  # counted in process
    redis.fail_with = None
    await limiter.hit("k")  # counted in Redis, which has not seen this key yet
    with pytest.raises(TooManyRequestsError):
        await limiter.hit("k")
    assert fallback is not None


# ----------------------------------------------------------------- wiring & health


async def test_login_is_limited_through_the_redis_limiter(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    redis = FakeRedis()
    app.state.rate_limiter, _ = limiter_for(redis, attempts=3)
    await register(client)
    statuses = [(await login(client, password="Wrong-passphrase-1")).status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    assert len(redis.counters) == 3  # ip + email + register (hashed keys, no raw values)


def test_no_url_means_no_client() -> None:
    assert create_redis_client(None) is None


def test_a_missing_redis_package_is_survivable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    with caplog.at_level(logging.WARNING):
        assert create_redis_client("redis://secret-host:6379/0") is None
    assert "not installed" in caplog.text
    assert "secret-host" not in caplog.text  # the URL is never logged


def test_the_app_starts_without_redis_even_when_a_url_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    try:
        app = create_app()
    finally:
        get_settings.cache_clear()
    assert app.state.redis is None
    assert isinstance(app.state.rate_limiter, InMemoryRateLimiter)


async def test_readiness_reports_redis_states() -> None:
    assert (await check_redis(None, None)).status == "not_configured"
    assert (await check_redis("redis://x", None)).status == "unchecked"

    redis = FakeRedis()
    assert (await check_redis("redis://x", redis)).status == "ok"

    redis.fail_with = ConnectionError("redis://user:secret@host")
    degraded = await check_redis("redis://x", redis)
    assert degraded.status == "degraded"
    assert "secret" not in (degraded.detail or "")


async def test_an_unreachable_redis_does_not_make_the_service_unready(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    redis = FakeRedis()
    redis.fail_with = ConnectionError("down")
    app.state.redis = redis
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, redis_url="redis://x/0"
    )
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["redis"]["status"] == "degraded"

    redis.fail_with = None
    assert (await client.get("/health/ready")).json()["checks"]["redis"]["status"] == "ok"


async def test_peek_reads_without_counting_and_blocks_at_the_limit() -> None:
    redis = FakeRedis()
    limiter, _ = limiter_for(redis, attempts=2)
    for _ in range(5):
        await limiter.peek("k")  # nothing recorded
    assert redis.counters == {}
    await limiter.hit("k")
    await limiter.hit("k")
    redis.now_ms += 20_000
    with pytest.raises(TooManyRequestsError) as error:
        await limiter.peek("k")
    assert error.value.headers == {"Retry-After": "40"}


async def test_peek_falls_back_when_redis_is_down() -> None:
    redis = FakeRedis()
    redis.fail_with = ConnectionError("down")
    limiter, _ = limiter_for(redis, attempts=1)
    await limiter.peek("k")
    await limiter.hit("k")
    with pytest.raises(TooManyRequestsError):
        await limiter.peek("k")
