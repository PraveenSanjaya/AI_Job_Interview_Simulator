from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings
from app.db.session import get_session
from app.db.types import UTCDateTime
from app.models.base import NAMING_CONVENTION, Base

pytestmark = pytest.mark.anyio


class _ScratchBase(DeclarativeBase):
    """Separate metadata so scratch tables never leak into the application schema."""


class _Stamp(_ScratchBase):
    __tablename__ = "_test_stamp"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    unused: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


def test_database_url_selects_async_drivers() -> None:
    assert (
        Settings(_env_file=None, database_url="postgresql://u:p@h/db").database_url
        == "postgresql+asyncpg://u:p@h/db"
    )
    assert (
        Settings(_env_file=None, database_url="postgres://u:p@h/db").database_url
        == "postgresql+asyncpg://u:p@h/db"
    )
    assert (
        Settings(_env_file=None, database_url="postgresql+asyncpg://u:p@h/db").database_url
        == "postgresql+asyncpg://u:p@h/db"
    )


def test_naming_convention_is_applied() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


async def test_engine_executes_queries(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as connection:
        result = await connection.exec_driver_sql("SELECT 1")
        assert result.scalar_one() == 1


async def test_utc_datetime_round_trips_as_aware_utc(
    db_engine: AsyncEngine, session: AsyncSession
) -> None:
    async with db_engine.begin() as connection:
        await connection.run_sync(_ScratchBase.metadata.create_all)
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    session.add(_Stamp(id=1, label="a", at=moment))
    await session.commit()
    session.expunge_all()
    loaded = (await session.execute(select(_Stamp))).scalar_one()
    assert loaded.at == moment
    assert loaded.at.tzinfo is not None


async def test_utc_datetime_rejects_naive_values(
    db_engine: AsyncEngine, session: AsyncSession
) -> None:
    async with db_engine.begin() as connection:
        await connection.run_sync(_ScratchBase.metadata.create_all)
    session.add(_Stamp(id=2, label="b", at=datetime(2026, 1, 1)))
    with pytest.raises(Exception, match="Naive datetime"):
        await session.commit()


async def test_session_dependency_yields_working_session(app: FastAPI) -> None:
    @app.get("/_test/db")
    async def db_route(db: AsyncSession = Depends(get_session)) -> dict[str, int]:  # noqa: B008
        result = await db.execute(select(1))
        return {"value": result.scalar_one()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/db")
    assert response.json() == {"value": 1}


async def test_session_dependency_reports_unconfigured_database(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.session_factory = None

    @app.get("/_test/db2")
    async def db_route(db: AsyncSession = Depends(get_session)) -> None:  # noqa: B008
        return None

    response = await client.get("/_test/db2")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
