"""Alembic migration tests.

Migrations are executed against a temporary SQLite file. The PostgreSQL migration
SQL is only *generated* (offline mode) and inspected; it is not executed against a
real PostgreSQL server in these tests.
"""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from tests.conftest import POSTGRES_TEST_URL

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "user_profiles",
    "education",
    "work_experience",
    "skills",
    "projects",
    "certifications",
    "resumes",
    "resume_analyses",
    "integration_sources",
    "integration_analyses",
}


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def table_names(db_file: Path) -> set[str]:
    with closing(sqlite3.connect(db_file)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows} - {"alembic_version"}


def test_upgrade_creates_schema_and_downgrade_removes_it(tmp_path: Path) -> None:
    db_file = tmp_path / "migrate.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    upgrade = run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    assert table_names(db_file) == EXPECTED_TABLES

    downgrade = run_alembic(url, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr
    assert table_names(db_file) == set()


def test_models_and_migrations_are_in_sync(tmp_path: Path) -> None:
    db_file = tmp_path / "drift.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    assert run_alembic(url, "upgrade", "head").returncode == 0

    check = run_alembic(url, "check")
    assert check.returncode == 0, f"Models changed without a migration:\n{check.stderr}"


def test_postgresql_sql_can_be_generated_offline() -> None:
    result = run_alembic("postgresql://user:pw@localhost/db", "upgrade", "head", "--sql")
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert "CREATE TABLE users" in sql
    assert "id UUID NOT NULL" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE CASCADE" in sql
    assert "pw" not in sql  # credentials never appear in generated SQL


def test_migrations_require_database_url() -> None:
    # An empty variable overrides any local .env value and means "not configured".
    result = run_alembic("", "upgrade", "head")
    assert result.returncode != 0
    assert "DATABASE_URL is not set" in result.stderr + result.stdout


@pytest.mark.skipif(
    POSTGRES_TEST_URL is None, reason="set TEST_DATABASE_URL to a PostgreSQL test database"
)
def test_migrations_apply_and_revert_on_postgresql() -> None:
    """Runs the real migration on PostgreSQL: upgrade, drift check, downgrade."""
    import asyncio

    from sqlalchemy import inspect, text

    from app.db.session import create_db_engine
    from tests.conftest import _assert_disposable

    assert POSTGRES_TEST_URL is not None
    _assert_disposable(POSTGRES_TEST_URL)

    async def tables() -> set[str]:
        engine = create_db_engine(POSTGRES_TEST_URL)
        try:
            async with engine.begin() as connection:
                return set(await connection.run_sync(lambda c: inspect(c).get_table_names()))
        finally:
            await engine.dispose()

    async def wipe() -> None:
        engine = create_db_engine(POSTGRES_TEST_URL)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA public CASCADE"))
                await connection.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    asyncio.run(wipe())
    upgrade = run_alembic(POSTGRES_TEST_URL, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    assert asyncio.run(tables()) - {"alembic_version"} == EXPECTED_TABLES

    check = run_alembic(POSTGRES_TEST_URL, "check")
    assert check.returncode == 0, check.stderr

    downgrade = run_alembic(POSTGRES_TEST_URL, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr
    assert asyncio.run(tables()) - {"alembic_version"} == set()
