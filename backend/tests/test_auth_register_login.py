import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tokens import hash_refresh_token
from app.models import RefreshToken, User
from tests.helpers import DEFAULT_PASSWORD, login, register

pytestmark = pytest.mark.anyio


async def test_register_creates_user_and_profile(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    response = await register(client, "Ada@Example.com ", full_name="  Ada Lovelace ")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"  # normalised
    assert body["role"] == "user"
    assert body["is_active"] is True
    user = (await session.execute(select(User))).scalar_one()
    assert user.profile.full_name == "Ada Lovelace"


async def test_register_response_never_contains_secrets(client: httpx.AsyncClient) -> None:
    response = await register(client)
    assert set(response.json()) == {"id", "email", "role", "is_active", "created_at"}
    assert DEFAULT_PASSWORD not in response.text
    assert "argon2" not in response.text


async def test_password_is_stored_as_argon2id_hash_only(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client)
    user = (await session.execute(select(User))).scalar_one()
    assert user.hashed_password.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in user.hashed_password


async def test_duplicate_email_is_rejected_case_insensitively(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    assert (await register(client, "dup@example.com")).status_code == 201
    response = await register(client, "DUP@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "S3cure-passphrase-42", "full_name": "A"},
        {"email": "a@example.com", "password": "short1", "full_name": "A"},
        {"email": "a@example.com", "password": "alllettersnodigits", "full_name": "A"},
        {"email": "a@example.com", "password": "1234567890123", "full_name": "A"},
        {"email": "a@example.com", "password": "x1" * 100, "full_name": "A"},
        {"email": "a@example.com", "password": "S3cure-passphrase-42", "full_name": "   "},
        {"email": "a@example.com", "password": "S3cure-passphrase-42"},
        {"password": "S3cure-passphrase-42", "full_name": "A"},
        {},
    ],
)
async def test_invalid_registration_data_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, payload: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert (await session.execute(select(User))).first() is None


async def test_validation_errors_do_not_echo_the_password(client: httpx.AsyncClient) -> None:
    secret = "tooshort"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": secret, "full_name": "A"},
    )
    assert response.status_code == 422
    assert secret not in response.text


async def test_login_returns_token_pair_and_stores_only_a_hash(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client)
    response = await login(client, "ADA@example.com")  # email is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["access_token"] and body["refresh_token"]

    stored = (await session.execute(select(RefreshToken))).scalar_one()
    assert stored.token_hash == hash_refresh_token(body["refresh_token"])
    assert stored.token_hash != body["refresh_token"]
    assert body["refresh_token"] not in stored.token_hash
    assert stored.revoked_at is None


async def test_wrong_password_and_unknown_email_are_indistinguishable(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    wrong_password = await login(client, password="Wrong-passphrase-1")
    unknown_email = await login(client, "nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    error_a, error_b = wrong_password.json()["error"], unknown_email.json()["error"]
    assert error_a["code"] == error_b["code"] == "invalid_credentials"
    assert error_a["message"] == error_b["message"]
    assert wrong_password.headers["www-authenticate"] == "Bearer"


async def test_unknown_email_still_performs_a_password_verification(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.services.auth.verify_against_dummy", calls.append)
    response = await login(client, "nobody@example.com")
    assert response.status_code == 401
    assert calls == [DEFAULT_PASSWORD]


async def test_disabled_account_cannot_log_in(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client)
    user = (await session.execute(select(User))).scalar_one()
    user.is_active = False
    await session.commit()
    response = await login(client)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_failed_login_issues_no_tokens(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client)
    await login(client, password="Wrong-passphrase-1")
    assert (await session.execute(select(RefreshToken))).first() is None


async def test_login_rejects_malformed_body(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "bad", "password": ""})
    assert response.status_code == 422
