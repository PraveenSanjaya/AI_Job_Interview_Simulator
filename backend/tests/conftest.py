from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.models import Base  # importing the package registers every model


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Isolated in-memory SQLite database per test.

    SQLite is a testing fallback only. PostgreSQL is the production database and
    is NOT exercised by these tests.
    """
    engine = create_db_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture
def app(db_engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app()
    application.state.engine = db_engine
    application.state.session_factory = session_factory
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
