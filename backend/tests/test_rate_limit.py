import httpx
import pytest
from fastapi import FastAPI

from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import InMemoryRateLimiter, NoopRateLimiter
from tests.helpers import login, register

pytestmark = pytest.mark.anyio


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_blocks_with_retry_after() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(3, 60, clock)
    for _ in range(3):
        limiter.hit("k")
    clock.now += 10
    with pytest.raises(TooManyRequestsError) as error:
        limiter.hit("k")
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "50"}


def test_window_slides_and_keys_are_independent() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(1, 60, clock)
    limiter.hit("a")
    limiter.hit("b")  # different key unaffected
    with pytest.raises(TooManyRequestsError):
        limiter.hit("a")
    clock.now += 60
    limiter.hit("a")  # window elapsed


def test_noop_limiter_never_blocks() -> None:
    limiter = NoopRateLimiter()
    for _ in range(1000):
        limiter.hit("k")


async def test_login_is_rate_limited_per_client(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.rate_limiter = InMemoryRateLimiter(3, 60)
    await register(client)  # register uses a separate key
    statuses = [(await login(client, password="Wrong-passphrase-1")).status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    blocked = await login(client, password="Wrong-passphrase-1")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1


async def test_login_is_rate_limited_per_target_email(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    # Allow plenty per IP but only a few attempts per account.
    class PerKeyLimiter(InMemoryRateLimiter):
        def hit(self, key: str) -> None:
            if key.startswith("login:ip:"):
                return
            super().hit(key)

    app.state.rate_limiter = PerKeyLimiter(2, 60)
    await register(client)
    results = [(await login(client, password="Wrong-passphrase-1")).status_code for _ in range(3)]
    assert results == [401, 401, 429]
    other_account = await login(client, "other@example.com", "Wrong-passphrase-1")
    assert other_account.status_code == 401


async def test_registration_is_rate_limited(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    codes = [(await register(client, f"u{i}@example.com")).status_code for i in range(3)]
    assert codes == [201, 201, 429]
