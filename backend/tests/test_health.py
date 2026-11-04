import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine

pytestmark = pytest.mark.anyio


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_unconfigured_dependencies(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.engine = None
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "not_configured"
    assert body["checks"]["redis"]["status"] == "not_configured"


async def test_readiness_reports_database_ok_after_real_probe(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/health/ready")).json()
    assert body["checks"]["database"]["status"] == "ok"


async def test_readiness_fails_when_database_unreachable(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    broken = create_db_engine("sqlite+aiosqlite:///C:/definitely/missing/dir/x.db")
    app.state.engine = broken
    response = await client.get("/health/ready")
    await broken.dispose()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == {"status": "error", "detail": "database connection failed"}
    assert "missing" not in response.text  # connection details are not leaked


async def test_redis_is_never_reported_ok_without_a_probe(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, redis_url="redis://x/0"
    )
    body = (await client.get("/health/ready")).json()
    assert body["checks"]["redis"]["status"] == "unchecked"


async def test_health_endpoints_are_not_versioned(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/health/live")).status_code == 404


async def test_openapi_docs_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health/live" in response.json()["paths"]
