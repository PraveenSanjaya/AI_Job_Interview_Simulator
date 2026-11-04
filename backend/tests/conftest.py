from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

    # Test-only routes that exercise the error handlers.
    @application.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @application.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Thing not found")

    @application.get("/_test/int/{value}")
    async def int_route(value: int) -> dict[str, int]:
        return {"value": value}

    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
