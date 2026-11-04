import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings

pytestmark = pytest.mark.anyio


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_never_reports_unconfigured_dependencies_as_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "not_configured"
    assert body["checks"]["redis"]["status"] == "not_configured"


async def test_readiness_does_not_claim_configured_but_unprobed_dependencies_are_ok(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, database_url="postgresql://x/y", redis_url="redis://x/0"
    )
    body = (await client.get("/health/ready")).json()
    assert body["checks"]["database"]["status"] == "unchecked"
    assert body["checks"]["redis"]["status"] == "unchecked"
    assert "ok" not in {check["status"] for check in body["checks"].values()}


async def test_health_endpoints_are_not_versioned(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/health/live")).status_code == 404


async def test_openapi_docs_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health/live" in response.json()["paths"]
