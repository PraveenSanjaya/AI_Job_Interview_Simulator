import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import Settings
from app.core.tokens import create_access_token
from app.models import User
from app.models.enums import UserRole
from tests.helpers import bearer, register, register_and_login

pytestmark = pytest.mark.anyio

ME = "/api/v1/auth/me"


async def test_me_returns_current_user(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client, "me@example.com")
    response = await client.get(ME, headers=bearer(tokens["access_token"]))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert set(body) == {"id", "email", "role", "is_active", "created_at"}


async def test_missing_credentials_are_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic abc", "token abc", "Bearer a.b.c"])
async def test_malformed_authorization_headers_are_rejected(
    client: httpx.AsyncClient, header: str
) -> None:
    response = await client.get(ME, headers={"Authorization": header})
    assert response.status_code == 401


async def test_expired_access_token_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    await register(client, "exp@example.com")
    user = (await session.execute(select(User))).scalar_one()
    token, _ = create_access_token(user.id, settings, now=datetime.now(UTC) - timedelta(hours=1))
    response = await client.get(ME, headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


async def test_token_with_invalid_signature_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    await register(client, "sig@example.com")
    user = (await session.execute(select(User))).scalar_one()
    forged = jwt.encode(
        {
            "sub": str(user.id),
            "iss": settings.jwt_issuer,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "type": "access",
        },
        "attacker-controlled-secret-attacker-controlled",
        algorithm="HS256",
    )
    response = await client.get(ME, headers=bearer(forged))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_refresh_token_cannot_be_used_as_access_token(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client)
    response = await client.get(ME, headers=bearer(tokens["refresh_token"]))
    assert response.status_code == 401


async def test_token_for_deleted_user_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    token, _ = create_access_token(uuid.uuid4(), settings)  # valid signature, no such user
    response = await client.get(ME, headers=bearer(token))
    assert response.status_code == 401


async def test_disabled_user_loses_access_immediately(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    user = (await session.execute(select(User))).scalar_one()
    user.is_active = False
    await session.commit()
    response = await client.get(ME, headers=bearer(tokens["access_token"]))
    assert response.status_code == 401


async def test_role_guard_allows_only_listed_roles(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    @app.get("/_test/admin")
    async def admin_only(_: User = Depends(require_roles(UserRole.ADMIN))) -> dict[str, bool]:  # noqa: B008
        return {"ok": True}

    tokens = await register_and_login(client)
    denied = await client.get("/_test/admin", headers=bearer(tokens["access_token"]))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"

    user = (await session.execute(select(User))).scalar_one()
    user.role = UserRole.ADMIN
    await session.commit()
    allowed = await client.get("/_test/admin", headers=bearer(tokens["access_token"]))
    assert allowed.status_code == 200


async def test_unauthenticated_request_to_role_guarded_route_is_401_not_403(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.get("/_test/admin2")
    async def admin_only(_: User = Depends(require_roles(UserRole.ADMIN))) -> dict[str, bool]:  # noqa: B008
        return {"ok": True}

    assert (await client.get("/_test/admin2")).status_code == 401
