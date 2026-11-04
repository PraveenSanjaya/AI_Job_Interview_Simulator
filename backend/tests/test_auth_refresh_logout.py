from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tokens import hash_refresh_token
from app.models import RefreshToken, User
from app.repositories.refresh_tokens import RefreshTokenRepository
from tests.helpers import DEFAULT_PASSWORD, login, register, register_and_login

pytestmark = pytest.mark.anyio


async def refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def logout(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/logout", json={"refresh_token": token})


async def all_tokens(session: AsyncSession) -> list[RefreshToken]:
    session.expire_all()
    result = await session.execute(select(RefreshToken).order_by(RefreshToken.created_at))
    return list(result.scalars())


async def test_refresh_rotates_the_token(client: httpx.AsyncClient, session: AsyncSession) -> None:
    first = await register_and_login(client)
    response = await refresh(client, first["refresh_token"])
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]

    old, new = await all_tokens(session)
    assert old.token_hash == hash_refresh_token(first["refresh_token"])
    assert old.revoked_at is not None
    assert new.revoked_at is None
    assert new.family_id == old.family_id  # same session lineage


async def test_rotated_refresh_token_can_be_chained(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client)
    for _ in range(3):
        response = await refresh(client, tokens["refresh_token"])
        assert response.status_code == 200
        tokens = response.json()


async def test_reusing_a_rotated_token_is_rejected_and_revokes_the_family(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    first = await register_and_login(client)
    second = (await refresh(client, first["refresh_token"])).json()

    replay = await refresh(client, first["refresh_token"])  # attacker replays the old token
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"

    # The legitimate holder's newest token is revoked too, forcing re-authentication.
    assert (await refresh(client, second["refresh_token"])).status_code == 401
    assert all(token.revoked_at is not None for token in await all_tokens(session))


async def test_unknown_and_malformed_refresh_tokens_are_rejected(
    client: httpx.AsyncClient,
) -> None:
    assert (await refresh(client, "does-not-exist")).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={})).status_code == 422
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": ""})
    ).status_code == 422


async def test_expired_refresh_token_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    stored = (await all_tokens(session))[0]
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    response = await refresh(client, tokens["refresh_token"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_fails_for_disabled_user(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    user = (await session.execute(select(User))).scalar_one()
    user.is_active = False
    await session.commit()
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


async def test_logout_revokes_refresh_token(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    response = await logout(client, tokens["refresh_token"])
    assert response.status_code == 204
    assert response.content == b""
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401
    assert all(token.revoked_at is not None for token in await all_tokens(session))


async def test_logout_revokes_descendant_tokens_of_the_session(
    client: httpx.AsyncClient,
) -> None:
    first = await register_and_login(client)
    second = (await refresh(client, first["refresh_token"])).json()
    assert (await logout(client, second["refresh_token"])).status_code == 204
    assert (await refresh(client, second["refresh_token"])).status_code == 401


async def test_logout_only_ends_the_current_session(client: httpx.AsyncClient) -> None:
    await register(client)
    laptop = (await login(client)).json()
    phone = (await login(client)).json()
    await logout(client, laptop["refresh_token"])
    assert (await refresh(client, laptop["refresh_token"])).status_code == 401
    assert (await refresh(client, phone["refresh_token"])).status_code == 200


async def test_logout_is_idempotent_and_does_not_reveal_token_validity(
    client: httpx.AsyncClient,
) -> None:
    tokens = await register_and_login(client)
    assert (await logout(client, tokens["refresh_token"])).status_code == 204
    assert (await logout(client, tokens["refresh_token"])).status_code == 204
    assert (await logout(client, "never-issued")).status_code == 204


async def test_revoke_if_active_only_succeeds_once(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register_and_login(client)
    token = (await all_tokens(session))[0]
    repo = RefreshTokenRepository(session)
    now = datetime.now(UTC)
    assert await repo.revoke_if_active(token.id, now) is True
    assert await repo.revoke_if_active(token.id, now) is False


async def test_new_login_after_logout_works(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client)
    await logout(client, tokens["refresh_token"])
    assert (await login(client, password=DEFAULT_PASSWORD)).status_code == 200
