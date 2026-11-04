"""Async SQLAlchemy engine, session factory and FastAPI session dependency."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from app.core.exceptions import ServiceUnavailableError


def create_db_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine. Connections are opened lazily on first use."""
    engine_kwargs: dict[str, Any] = {"echo": echo}
    if not url.startswith("sqlite"):
        engine_kwargs["pool_pre_ping"] = True
    elif url.rstrip("/").endswith("://") or ":memory:" in url:
        # An in-memory SQLite database lives in one connection; share it (tests only).
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_async_engine(url, **engine_kwargs)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless enabled per connection.
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: ConnectionPoolEntry) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the application's session factory."""
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if factory is None:
        raise ServiceUnavailableError("Database is not configured", code="database_unavailable")
    async with factory() as session:
        yield session
