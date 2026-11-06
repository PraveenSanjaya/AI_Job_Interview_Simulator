"""Shared helpers for API tests."""

from typing import Any

import httpx

DEFAULT_PASSWORD = "S3cure-passphrase-42"


async def register(
    client: httpx.AsyncClient,
    email: str = "ada@example.com",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Ada Lovelace",
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


async def login(
    client: httpx.AsyncClient,
    email: str = "ada@example.com",
    password: str = DEFAULT_PASSWORD,
) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def register_and_login(
    client: httpx.AsyncClient,
    email: str = "ada@example.com",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Ada Lovelace",
) -> dict[str, Any]:
    created = await register(client, email, password, full_name)
    assert created.status_code == 202, created.text
    response = await login(client, email, password)
    assert response.status_code == 200, response.text
    return session_tokens(response)


def session_tokens(response: httpx.Response) -> dict[str, Any]:
    """The access token from the body plus the refresh token from its HttpOnly cookie
    (the body never contains it). Tests use this to drive the legacy body path and to
    inspect the cookie."""
    assert "refresh_token" not in response.json()
    tokens: dict[str, Any] = response.json()
    cookie = response.cookies.get("refresh_token")
    assert cookie, "the refresh cookie was not set"
    tokens["refresh_token"] = cookie
    return tokens


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
