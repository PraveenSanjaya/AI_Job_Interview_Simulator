"""Browser access: only the configured frontend origins may call the API."""

import httpx
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.anyio

ORIGIN = "http://localhost:5173"


async def test_preflight_from_the_frontend_is_allowed(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/profile",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "PUT" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


async def test_other_origins_get_no_cors_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    preflight = await client.options(
        "/api/v1/profile",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in preflight.headers


async def test_error_responses_carry_cors_headers_and_expose_the_request_id(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/profile", headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


async def test_extra_origins_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings
    from app.main import create_app

    custom = Settings(
        _env_file=None,
        jwt_secret_key="test-only-jwt-secret-0123456789abcdef-xyz",
        cors_allowed_origins=["https://app.example.com/"],
    )
    monkeypatch.setattr("app.main.get_settings", lambda: custom)
    application: FastAPI = create_app()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        for origin in ("https://app.example.com", ORIGIN):
            response = await http.options(
                "/api/v1/profile",
                headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
            )
            assert response.headers["access-control-allow-origin"] == origin
