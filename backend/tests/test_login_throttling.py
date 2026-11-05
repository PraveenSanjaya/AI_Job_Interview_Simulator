"""Sign-in throttling must slow attackers without letting them lock the owner out."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import InMemoryRateLimiter
from tests.helpers import DEFAULT_PASSWORD, login, register
from tests.test_rate_limit import FakeClock

pytestmark = pytest.mark.anyio

WRONG = "Wrong-passphrase-1"


@asynccontextmanager
async def client_from(app: FastAPI, address: str) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose requests appear to come from ``address``."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(address, 4242))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_an_attacker_cannot_lock_the_owner_out(app: FastAPI) -> None:
    app.state.rate_limiter = InMemoryRateLimiter(5, 60)
    async with client_from(app, "10.0.0.1") as owner, client_from(app, "203.0.113.66") as attacker:
        assert (await register(owner)).status_code == 202

        # The attacker hammers the owner's account from their own address.
        statuses = [(await login(attacker, password=WRONG)).status_code for _ in range(12)]
        assert statuses[:5] == [401] * 5
        assert set(statuses[5:]) == {429}  # the attacker is throttled...

        # ...but the owner, from a different address, signs in normally.
        response = await login(owner)
        assert response.status_code == 200, response.text


async def test_the_attacker_cannot_even_use_the_correct_password_from_a_throttled_address(
    app: FastAPI,
) -> None:
    """Throttling is per address and account; it is not a way to probe for the password."""
    app.state.rate_limiter = InMemoryRateLimiter(3, 60)
    async with client_from(app, "10.0.0.1") as owner, client_from(app, "203.0.113.66") as attacker:
        await register(owner)
        for _ in range(3):
            await login(attacker, password=WRONG)
        assert (await login(attacker, password=DEFAULT_PASSWORD)).status_code == 429


async def test_the_owners_own_typos_do_not_block_a_later_correct_attempt(app: FastAPI) -> None:
    app.state.rate_limiter = InMemoryRateLimiter(5, 60)
    async with client_from(app, "10.0.0.1") as owner:
        await register(owner)
        for _ in range(2):
            assert (await login(owner, password=WRONG)).status_code == 401
        assert (await login(owner)).status_code == 200


async def test_failures_spread_over_many_addresses_hit_the_account_wide_ceiling(
    app: FastAPI,
) -> None:
    """Distributed guessing is bounded; this is also the documented residual risk."""
    app.state.login_failure_limiter = InMemoryRateLimiter(3, 900)
    async with client_from(app, "10.0.0.1") as owner:
        await register(owner)
    for i in range(3):
        async with client_from(app, f"198.51.100.{i}") as bot:
            assert (await login(bot, password=WRONG)).status_code == 401
    async with client_from(app, "198.51.100.200") as bot:
        blocked = await login(bot, password=WRONG)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert int(blocked.headers["retry-after"]) >= 1


async def test_only_failures_count_towards_the_account_wide_ceiling(app: FastAPI) -> None:
    app.state.login_failure_limiter = InMemoryRateLimiter(3, 900)
    async with client_from(app, "10.0.0.1") as owner:
        await register(owner)
    for i in range(10):  # many successful sign-ins from many addresses
        async with client_from(app, f"192.0.2.{i}") as device:
            assert (await login(device)).status_code == 200


async def test_the_account_wide_ceiling_applies_equally_to_unknown_accounts(
    app: FastAPI,
) -> None:
    """No difference in behaviour between an existing and a non-existing e-mail address."""
    app.state.login_failure_limiter = InMemoryRateLimiter(2, 900)
    codes = []
    for i in range(4):
        async with client_from(app, f"198.51.100.{i}") as bot:
            codes.append((await login(bot, "nobody@example.com", WRONG)).status_code)
    assert codes == [401, 401, 429, 429]


async def test_the_account_wide_ceiling_recovers_after_its_window(app: FastAPI) -> None:
    clock = FakeClock()
    app.state.login_failure_limiter = InMemoryRateLimiter(2, 900, clock)
    async with client_from(app, "10.0.0.1") as owner:
        await register(owner)
    for i in range(2):
        async with client_from(app, f"198.51.100.{i}") as bot:
            await login(bot, password=WRONG)
    async with client_from(app, "10.0.0.1") as owner:
        assert (await login(owner)).status_code == 429
        clock.now += 901
        assert (await login(owner)).status_code == 200


# ---------------------------------------------------------------- peek semantics


async def test_peek_never_records_an_attempt() -> None:
    limiter = InMemoryRateLimiter(2, 60)
    for _ in range(10):
        await limiter.peek("k")  # does not consume the budget
    await limiter.hit("k")
    await limiter.hit("k")
    with pytest.raises(TooManyRequestsError):
        await limiter.peek("k")
    with pytest.raises(TooManyRequestsError):
        await limiter.hit("k")


async def test_peek_follows_the_window() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(1, 60, clock)
    await limiter.hit("k")
    with pytest.raises(TooManyRequestsError) as error:
        await limiter.peek("k")
    assert error.value.headers == {"Retry-After": "60"}
    clock.now += 60
    await limiter.peek("k")
