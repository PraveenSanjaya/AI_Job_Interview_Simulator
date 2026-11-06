"""Concurrent use of one refresh token must succeed at most once.

Runs against a file-backed SQLite database (independent connections) and, when
``TEST_DATABASE_URL`` points at PostgreSQL, against PostgreSQL too.
"""

import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.models import RefreshToken
from tests.helpers import register_and_login, session_tokens

pytestmark = pytest.mark.anyio


async def refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def stored_tokens(engine: AsyncEngine) -> list[RefreshToken]:
    async with create_session_factory(engine)() as session:
        return list((await session.execute(select(RefreshToken))).scalars())


@pytest.mark.parametrize("parallel", [2, 6])
async def test_only_one_of_many_concurrent_refreshes_succeeds(
    concurrent_client: httpx.AsyncClient, concurrent_engine: AsyncEngine, parallel: int
) -> None:
    tokens = await register_and_login(concurrent_client)

    responses = await asyncio.gather(
        *(refresh(concurrent_client, tokens["refresh_token"]) for _ in range(parallel))
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] + [401] * (parallel - 1), statuses
    for failed in (r for r in responses if r.status_code == 401):
        assert failed.json()["error"]["code"] == "invalid_refresh_token"

    rows = await stored_tokens(concurrent_engine)
    original = next(r for r in rows if r.revoked_at is not None)
    assert original.revoked_at is not None
    # The original is always consumed exactly once; the family never has two live
    # tokens, even though several requests presented the same credential.
    live = [r for r in rows if r.revoked_at is None]
    assert len(live) <= 1


async def test_loser_of_a_race_cannot_keep_a_session_alive(
    concurrent_client: httpx.AsyncClient, concurrent_engine: AsyncEngine
) -> None:
    """After a double-submit, no token handed out to the loser exists (it got a 401)
    and the winner's token is the only one that may still work."""
    tokens = await register_and_login(concurrent_client)
    first, second = await asyncio.gather(
        refresh(concurrent_client, tokens["refresh_token"]),
        refresh(concurrent_client, tokens["refresh_token"]),
    )
    assert {first.status_code, second.status_code} == {200, 401}
    winner = first if first.status_code == 200 else second

    # The old token is dead for everyone from now on.
    assert (await refresh(concurrent_client, tokens["refresh_token"])).status_code == 401

    # The winner's token is revoked by the reuse detection (reuse revokes the family),
    # or - if the winner committed after the loser's revocation - still valid once.
    follow_up = await refresh(concurrent_client, session_tokens(winner)["refresh_token"])
    assert follow_up.status_code in (200, 401)
    rows = await stored_tokens(concurrent_engine)
    assert sum(1 for r in rows if r.revoked_at is None) <= 1


async def test_concurrent_logins_each_get_independent_sessions(
    concurrent_client: httpx.AsyncClient, concurrent_engine: AsyncEngine
) -> None:
    await register_and_login(concurrent_client)
    responses = await asyncio.gather(
        *(
            concurrent_client.post(
                "/api/v1/auth/login",
                json={"email": "ada@example.com", "password": "S3cure-passphrase-42"},
            )
            for _ in range(4)
        )
    )
    assert [r.status_code for r in responses] == [200] * 4
    refresh_tokens = {session_tokens(r)["refresh_token"] for r in responses}
    assert len(refresh_tokens) == 4
    rows = await stored_tokens(concurrent_engine)
    assert len({r.family_id for r in rows}) == 5  # 1 initial login + 4 concurrent ones


async def test_concurrent_registration_of_same_email_creates_one_account(
    concurrent_client: httpx.AsyncClient, concurrent_engine: AsyncEngine
) -> None:
    payload = {"email": "race@example.com", "password": "S3cure-passphrase-42", "full_name": "R"}
    responses = await asyncio.gather(
        *(concurrent_client.post("/api/v1/auth/register", json=payload) for _ in range(5))
    )
    assert {r.status_code for r in responses} == {202}  # identical outcome for everyone
    assert len({r.text for r in responses}) == 1
    from app.models import User

    async with create_session_factory(concurrent_engine)() as session:
        users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
