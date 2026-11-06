"""Request-size caps, response hardening headers and production-only exposure."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_an_oversized_json_body_is_refused_before_authentication(
    client: httpx.AsyncClient,
) -> None:
    body = json.dumps({"email": "a@example.com", "password": "x" * (2 * 1024 * 1024)})
    response = await client.post(
        "/api/v1/auth/login", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_an_oversized_body_without_a_declared_length_is_refused(
    client: httpx.AsyncClient,
) -> None:
    async def chunks() -> AsyncIterator[
        bytes
    ]:  # no Content-Length: streamed, so only counting can stop it
        for _ in range(40):
            yield b"x" * (64 * 1024)

    response = await client.post(
        "/api/v1/auth/register",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_normal_json_bodies_still_work(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


async def test_uploads_keep_their_own_larger_limit(client: httpx.AsyncClient) -> None:
    # 2 MiB is over the JSON cap but under the 5 MiB upload limit: it must reach the route
    # (which rejects it for lacking a valid session), not be cut off as "too large".
    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("cv.txt", b"a" * (2 * 1024 * 1024), "text/plain")},
    )
    assert response.status_code == 401


async def test_api_responses_are_hardened_and_not_cacheable(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


async def test_error_responses_from_the_size_cap_are_hardened_too(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        content=b"x" * (2 * 1024 * 1024),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"


def test_api_documentation_is_published_in_development_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    def build(env: str) -> int:
        get_settings.cache_clear()
        monkeypatch.setenv("APP_ENV", env)
        monkeypatch.setenv("JWT_SECRET_KEY", "p" * 40)
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
        try:
            app = create_app()
            return len(
                [r for r in app.routes if getattr(r, "path", "") in ("/docs", "/openapi.json")]
            )
        finally:
            get_settings.cache_clear()

    assert build("development") == 2
    assert build("production") == 0


def test_the_json_body_cap_is_configurable_within_safe_bounds() -> None:
    assert Settings(_env_file=None).max_json_body_bytes == 1024 * 1024
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_json_body_bytes=100)
