"""Access tokens end with the login session that issued them (not at expiry)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.tokens import create_access_token, decode_access_token
from app.models import RefreshToken, User
from tests.helpers import bearer, login, register_and_login

pytestmark = pytest.mark.anyio

ME = "/api/v1/auth/me"


async def me(client: httpx.AsyncClient, tokens: dict[str, str]) -> httpx.Response:
    return await client.get(ME, headers=bearer(tokens["access_token"]))


async def test_logout_ends_the_access_token_immediately(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client)
    assert (await me(client, tokens)).status_code == 200

    out = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 204

    after = await me(client, tokens)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "session_ended"


async def test_logging_out_one_session_leaves_the_users_other_sessions_alone(
    client: httpx.AsyncClient,
) -> None:
    first = await register_and_login(client)
    second = (await login(client)).json()  # a second device
    await client.post("/api/v1/auth/logout", json={"refresh_token": first["refresh_token"]})

    assert (await me(client, first)).status_code == 401
    assert (await me(client, second)).status_code == 200


async def test_refreshing_keeps_the_session_alive_and_the_new_token_works(
    client: httpx.AsyncClient,
) -> None:
    old = await register_and_login(client)
    new = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    ).json()
    assert (await me(client, new)).status_code == 200
    # Rotation does not end the session, so the previous short-lived token still works
    # until it expires (this is what keeps parallel in-flight requests from failing).
    assert (await me(client, old)).status_code == 200


async def test_logout_after_a_refresh_ends_every_token_of_the_session(
    client: httpx.AsyncClient,
) -> None:
    old = await register_and_login(client)
    new = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    ).json()
    await client.post("/api/v1/auth/logout", json={"refresh_token": new["refresh_token"]})
    assert (await me(client, old)).status_code == 401
    assert (await me(client, new)).status_code == 401


async def test_detected_refresh_token_reuse_also_ends_the_access_tokens(
    client: httpx.AsyncClient,
) -> None:
    first = await register_and_login(client)
    second = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401  # a stolen token was replayed

    # Both the thief's and the victim's access tokens die with the session.
    assert (await me(client, first)).status_code == 401
    assert (await me(client, second)).status_code == 401


async def test_a_session_that_expired_by_time_rejects_its_access_tokens(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    await session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()
    assert (await me(client, tokens)).status_code == 401


async def test_tokens_issued_before_sessions_were_bound_still_work_until_they_expire(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    """Deploying this change must not sign anyone out: old tokens have no ``sid``."""
    await register_and_login(client)
    user_id = (await session.execute(select(User.id))).scalar_one()
    legacy, _ = create_access_token(user_id, settings)  # no session id
    assert "sid" not in jwt.decode(legacy, options={"verify_signature": False})
    response = await client.get(ME, headers=bearer(legacy))
    assert response.status_code == 200


async def test_a_token_naming_an_unknown_session_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    await register_and_login(client)
    user_id = (await session.execute(select(User.id))).scalar_one()
    forged, _ = create_access_token(user_id, settings, session_id=uuid.uuid4())
    response = await client.get(ME, headers=bearer(forged))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_ended"


async def test_a_malformed_session_claim_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    await register_and_login(client)
    user_id = (await session.execute(select(User.id))).scalar_one()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "type": "access",
            "sid": "not-a-uuid",
        },
        settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else "",
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get(ME, headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_new_access_tokens_carry_the_session_id() -> None:
    settings = Settings(
        _env_file=None, jwt_secret_key="unit-test-secret-that-is-long-enough-123456"
    )
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(user_id, settings, session_id=session_id)
    claims = decode_access_token(token, settings)
    assert claims.session_id == session_id and claims.user_id == user_id
