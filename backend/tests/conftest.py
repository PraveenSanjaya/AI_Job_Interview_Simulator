"""Shared fixtures.

By default every test gets an isolated in-memory SQLite database (a testing
fallback only). Set ``TEST_DATABASE_URL`` to a *dedicated, disposable* PostgreSQL
database (its name must contain "test") to run the same suite against PostgreSQL:

    TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/interview_test pytest
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.core.rate_limit import InMemoryRateLimiter
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.models import Base  # importing the package registers every model
from app.storage.local import LocalStorage
from tests.fakes_github import FakeGitHubClient
from tests.fakes_portfolio import FakeWeb

TEST_JWT_SECRET = "test-only-jwt-secret-0123456789abcdef-xyz"
_RAW_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
TEST_DATABASE_URL = (
    Settings(_env_file=None, database_url=_RAW_TEST_DATABASE_URL).database_url
    if _RAW_TEST_DATABASE_URL
    else None
)
POSTGRES_TEST_URL = (
    TEST_DATABASE_URL if TEST_DATABASE_URL and TEST_DATABASE_URL.startswith("postgresql") else None
)


def _assert_disposable(url: str) -> None:
    """Tests drop and recreate all tables, so never run them on a non-test database."""
    database = make_url(url).database or ""
    if "test" not in database.lower():
        raise RuntimeError(
            f"Refusing to reset database {database!r}: TEST_DATABASE_URL must point to a "
            "disposable database whose name contains 'test'."
        )


async def _reset_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def build_app(engine: AsyncEngine, settings: Settings, storage_root: Path) -> FastAPI:
    application = create_app()
    application.state.storage = LocalStorage(storage_root)
    application.state.github_client = FakeGitHubClient()
    application.state.portfolio_fetcher = FakeWeb().fetcher()
    application.state.engine = engine
    application.state.session_factory = create_session_factory(engine)
    application.state.rate_limiter = InMemoryRateLimiter(1000, 60)
    application.dependency_overrides[get_settings] = lambda: settings

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
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """A fresh database per test: in-memory SQLite, or PostgreSQL if configured."""
    if TEST_DATABASE_URL:
        _assert_disposable(TEST_DATABASE_URL)
        engine = create_db_engine(TEST_DATABASE_URL)
    else:
        engine = create_db_engine("sqlite+aiosqlite://")
    await _reset_schema(engine)
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
def settings() -> Settings:
    """One fixed settings object (a fresh Settings() would generate a new JWT secret)."""
    return Settings(_env_file=None, jwt_secret_key=TEST_JWT_SECRET)


@pytest.fixture
def app(db_engine: AsyncEngine, settings: Settings, tmp_path: Path) -> FastAPI:
    return build_app(db_engine, settings, tmp_path / "storage")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture(params=["sqlite-file", "postgresql"])
async def concurrent_engine(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[AsyncEngine]:
    """An engine whose connections are genuinely independent (needed for race tests).

    The default in-memory SQLite database shares one connection, so it cannot
    exercise concurrent transactions. The PostgreSQL variant is skipped unless
    ``TEST_DATABASE_URL`` points at PostgreSQL.
    """
    if request.param == "postgresql":
        if POSTGRES_TEST_URL is None:
            pytest.skip("set TEST_DATABASE_URL to a PostgreSQL test database to run this")
        _assert_disposable(POSTGRES_TEST_URL)
        engine = create_db_engine(POSTGRES_TEST_URL)
    else:
        engine = create_db_engine(f"sqlite+aiosqlite:///{(tmp_path / 'race.db').as_posix()}")
    await _reset_schema(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def concurrent_client(
    concurrent_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(concurrent_engine, settings, tmp_path / "storage")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
