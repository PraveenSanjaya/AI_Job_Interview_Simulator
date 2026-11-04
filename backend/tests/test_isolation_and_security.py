import logging

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Skill, UserProfile
from tests.helpers import DEFAULT_PASSWORD, bearer, login, register_and_login
from tests.test_profile import full_profile

pytestmark = pytest.mark.anyio

PROFILE = "/api/v1/profile"


async def two_users(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    ada = await register_and_login(client, "ada@example.com", full_name="Ada")
    bob = await register_and_login(client, "bob@example.com", full_name="Bob")
    return bearer(ada["access_token"]), bearer(bob["access_token"])


async def test_each_user_only_sees_their_own_profile(client: httpx.AsyncClient) -> None:
    ada, bob = await two_users(client)
    await client.put(PROFILE, json=full_profile(headline="Ada's headline"), headers=ada)

    ada_view = (await client.get(PROFILE, headers=ada)).json()
    bob_view = (await client.get(PROFILE, headers=bob)).json()
    assert ada_view["email"] == "ada@example.com"
    assert ada_view["headline"] == "Ada's headline"
    assert bob_view["email"] == "bob@example.com"
    assert bob_view["full_name"] == "Bob"
    assert bob_view["headline"] is None
    assert bob_view["skills"] == [] and bob_view["education"] == []


async def test_updating_one_profile_never_changes_another(client: httpx.AsyncClient) -> None:
    ada, bob = await two_users(client)
    await client.put(PROFILE, json=full_profile(headline="Ada"), headers=ada)
    await client.put(PROFILE, json=full_profile(headline="Bob", skills=[]), headers=bob)

    ada_view = (await client.get(PROFILE, headers=ada)).json()
    assert ada_view["headline"] == "Ada"
    assert len(ada_view["skills"]) == 3
    assert (await client.get(f"{PROFILE}/skills", headers=bob)).json() == []


async def test_identical_skill_names_are_allowed_across_users(client: httpx.AsyncClient) -> None:
    ada, bob = await two_users(client)
    assert (await client.put(PROFILE, json=full_profile(), headers=ada)).status_code == 200
    assert (await client.put(PROFILE, json=full_profile(), headers=bob)).status_code == 200


async def test_child_rows_belong_to_the_correct_profile(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    ada, bob = await two_users(client)
    await client.put(
        PROFILE,
        json=full_profile(full_name="Ada", skills=[{"name": "Rust", "category": "technical"}]),
        headers=ada,
    )
    await client.put(
        PROFILE,
        json=full_profile(full_name="Bob", skills=[{"name": "Go", "category": "technical"}]),
        headers=bob,
    )
    profiles = {
        p.full_name: p.id for p in (await session.execute(select(UserProfile))).scalars().all()
    }
    skills = (await session.execute(select(Skill))).scalars().all()
    owners = {skill.name: skill.profile_id for skill in skills}
    assert owners == {"Rust": profiles["Ada"], "Go": profiles["Bob"]}


async def test_token_of_one_user_cannot_be_used_to_act_as_another(
    client: httpx.AsyncClient,
) -> None:
    """Tokens are bound to their subject: identity comes only from the verified token."""
    ada, bob = await two_users(client)
    me_ada = (await client.get("/api/v1/auth/me", headers=ada)).json()
    me_bob = (await client.get("/api/v1/auth/me", headers=bob)).json()
    assert me_ada["id"] != me_bob["id"]
    assert me_ada["email"] == "ada@example.com"


async def test_revoking_one_users_session_does_not_affect_another(
    client: httpx.AsyncClient,
) -> None:
    ada = await register_and_login(client, "ada@example.com")
    bob = await register_and_login(client, "bob@example.com")
    await client.post("/api/v1/auth/logout", json={"refresh_token": ada["refresh_token"]})
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": bob["refresh_token"]})
    ).status_code == 200


async def test_no_endpoint_response_contains_hashes_or_the_password(
    client: httpx.AsyncClient,
) -> None:
    tokens = await register_and_login(client)
    headers = bearer(tokens["access_token"])
    bodies = [
        (await client.get("/api/v1/auth/me", headers=headers)).text,
        (await client.get(PROFILE, headers=headers)).text,
        (await client.put(PROFILE, json=full_profile(), headers=headers)).text,
        (await client.get(f"{PROFILE}/skills", headers=headers)).text,
    ]
    for body in bodies:
        assert DEFAULT_PASSWORD not in body
        assert "argon2" not in body
        assert "hashed_password" not in body
        assert "token_hash" not in body


async def test_credentials_and_tokens_never_appear_in_logs(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        tokens = await register_and_login(client)
        await client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))
        await login(client, password="Wrong-passphrase-1")
    logged = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    for secret in (DEFAULT_PASSWORD, "Wrong-passphrase-1", tokens["access_token"]):
        assert secret not in logged
    assert tokens["refresh_token"] not in logged


async def test_openapi_documents_bearer_security_for_protected_routes(
    client: httpx.AsyncClient,
) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert spec["paths"]["/api/v1/profile"]["get"]["security"]
    assert "security" not in spec["paths"]["/api/v1/auth/login"]["post"]
