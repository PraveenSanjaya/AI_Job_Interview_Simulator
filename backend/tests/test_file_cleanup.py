"""Retryable removal of stored files after account deletion, with the account already gone."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.cleanup import run as run_cli
from app.core.config import get_settings
from app.db.session import create_db_engine, create_session_factory
from app.models import Base, PendingFileDeletion, User
from app.services.file_cleanup import (
    CLAIM_LEASE,
    ESCALATE_AFTER_ATTEMPTS,
    MAX_BACKOFF,
    backoff_after,
    claim,
    cleanup_loop,
    pending_summary,
    run_file_cleanup,
)
from app.storage.base import StorageError, new_storage_key
from app.storage.local import LocalStorage
from tests.fakes import SAMPLE_RESUME
from tests.helpers import DEFAULT_PASSWORD, bearer, register_and_login
from tests.samples import make_txt

pytestmark = pytest.mark.anyio

DELETE = "/api/v1/auth/delete-account"


class FlakyStorage(LocalStorage):
    """Fails to remove a namespace until ``healthy`` is switched on."""

    healthy = False
    calls = 0

    async def delete_namespace(self, owner_id: uuid.UUID) -> int:
        self.calls += 1
        if not self.healthy:
            raise StorageError("disk is read-only")
        return await super().delete_namespace(owner_id)


async def pending_rows(session: AsyncSession) -> list[PendingFileDeletion]:
    session.expire_all()
    return list((await session.execute(select(PendingFileDeletion))).scalars())


async def delete_account_with_failing_storage(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, email: str = "gone@example.com"
) -> tuple[FlakyStorage, uuid.UUID, httpx.Response]:
    tokens = await register_and_login(client, email)
    headers = bearer(tokens["access_token"])
    uploaded = await client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("cv.txt", make_txt(SAMPLE_RESUME.splitlines()), "text/plain")},
    )
    assert uploaded.status_code == 201
    storage = FlakyStorage(tmp_path / "storage")
    app.state.storage = storage
    owner = next(p for p in (tmp_path / "storage").iterdir() if p.is_dir())
    response = await client.post(DELETE, headers=headers, json={"password": DEFAULT_PASSWORD})
    return storage, uuid.UUID(hex=owner.name), response


async def test_a_failed_file_removal_leaves_a_durable_record_without_personal_data(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    storage, owner, response = await delete_account_with_failing_storage(app, client, tmp_path)
    assert response.json() == {"deleted": True, "stored_files_removed": False}

    (record,) = await pending_rows(session)
    assert record.storage_namespace == owner.hex
    assert record.attempts == 1 and record.last_attempt_at is not None
    assert record.next_attempt_at > datetime.now(UTC)  # backoff, not an instant retry loop
    # The account is gone, but the record is not tied to it and carries nothing personal.
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 0
    assert set(PendingFileDeletion.__table__.columns.keys()) == {
        "id",
        "storage_namespace",
        "created_at",
        "attempts",
        "last_attempt_at",
        "next_attempt_at",
    }
    assert any((tmp_path / "storage" / owner.hex).iterdir())  # the file is still on disk
    assert storage.calls == 1


async def test_the_sweeper_removes_the_files_once_storage_recovers(
    app: FastAPI,
    client: httpx.AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    storage, owner, _ = await delete_account_with_failing_storage(app, client, tmp_path)
    later = datetime.now(UTC) + timedelta(hours=1)

    # Still broken: the retry is recorded, nothing is lost, the backoff grows.
    report = await run_file_cleanup(session_factory, storage, now=later)
    assert (report.attempted, report.removed, report.failed) == (1, 0, 1)
    (record,) = await pending_rows(session)
    assert record.attempts == 2
    assert record.next_attempt_at == later + backoff_after(2)

    # Storage is fixed; the next due round finishes the job.
    storage.healthy = True
    report = await run_file_cleanup(session_factory, storage, now=later + timedelta(hours=2))
    assert (report.attempted, report.removed, report.failed) == (1, 1, 0)
    assert await pending_rows(session) == []
    assert not (tmp_path / "storage" / owner.hex).exists()


async def test_records_are_not_retried_before_they_are_due(
    app: FastAPI,
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    storage, _, _ = await delete_account_with_failing_storage(app, client, tmp_path)
    storage.healthy = True
    report = await run_file_cleanup(session_factory, storage)  # now: still inside the backoff
    assert report.attempted == 0


async def test_the_sweeper_only_touches_the_namespaces_it_was_asked_to_remove(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    storage = LocalStorage(tmp_path)
    gone, bystander = uuid.uuid4(), uuid.uuid4()
    await storage.put(new_storage_key(gone), b"old")
    keep_key = new_storage_key(bystander)
    await storage.put(keep_key, b"keep")
    session.add(PendingFileDeletion(storage_namespace=gone.hex, next_attempt_at=datetime.now(UTC)))
    await session.commit()

    report = await run_file_cleanup(session_factory, storage)
    assert report.removed == 1
    assert await storage.get(keep_key) == b"keep"
    assert not (tmp_path / gone.hex).exists()


async def test_a_namespace_that_is_already_gone_still_clears_its_record(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    session.add(
        PendingFileDeletion(storage_namespace=uuid.uuid4().hex, next_attempt_at=datetime.now(UTC))
    )
    await session.commit()
    report = await run_file_cleanup(session_factory, LocalStorage(tmp_path))
    assert report.removed == 1 and await pending_rows(session) == []


async def test_a_corrupt_record_backs_off_instead_of_crashing_the_sweeper(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    session.add(
        PendingFileDeletion(storage_namespace="not-a-uuid", next_attempt_at=datetime.now(UTC))
    )
    await session.commit()
    report = await run_file_cleanup(session_factory, LocalStorage(tmp_path))
    assert report.failed == 1
    (record,) = await pending_rows(session)
    assert record.attempts == 1


async def test_workers_with_independent_connections_never_process_the_same_record_twice(
    concurrent_engine: AsyncEngine, tmp_path: Path
) -> None:
    """Separate connections (file-backed SQLite; PostgreSQL when configured, otherwise
    skipped) stand in for separate worker processes."""
    factories = [create_session_factory(concurrent_engine) for _ in range(4)]

    class CountingStorage(LocalStorage):
        removed: list[uuid.UUID]

        async def delete_namespace(self, owner_id: uuid.UUID) -> int:
            self.removed.append(owner_id)
            await asyncio.sleep(0.01)  # widen the window in which a second worker could race
            return await super().delete_namespace(owner_id)

    storage = CountingStorage(tmp_path / "files")
    storage.removed = []
    async with factories[0]() as db:
        for _ in range(8):
            owner = uuid.uuid4()
            await storage.put(new_storage_key(owner), b"x")
            db.add(
                PendingFileDeletion(storage_namespace=owner.hex, next_attempt_at=datetime.now(UTC))
            )
        await db.commit()

    reports = await asyncio.gather(*(run_file_cleanup(f, storage) for f in factories))
    assert sum(r.failed for r in reports) == 0
    assert sum(r.removed for r in reports) == 8
    assert len(storage.removed) == len(set(storage.removed)) == 8  # each exactly once
    async with factories[0]() as db:
        assert (
            await db.execute(select(func.count()).select_from(PendingFileDeletion))
        ).scalar_one() == 0
    assert not [p for p in (tmp_path / "files").rglob("*") if p.is_file()]


async def test_a_claimed_record_cannot_be_claimed_again_until_its_lease_expires(
    session: AsyncSession,
) -> None:
    session.add(
        PendingFileDeletion(storage_namespace=uuid.uuid4().hex, next_attempt_at=datetime.now(UTC))
    )
    await session.commit()
    record = (await pending_rows(session))[0]
    now = datetime.now(UTC)
    assert await claim(session, record.id, now) is not None
    assert await claim(session, record.id, now) is None  # a second worker is turned away
    assert await claim(session, record.id, now + CLAIM_LEASE + timedelta(seconds=1)) is not None
    # a worker that died holding the lease does not strand the record forever


async def test_one_bad_record_does_not_stop_the_others_from_being_cleaned(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    storage = LocalStorage(tmp_path)
    good = uuid.uuid4()
    await storage.put(new_storage_key(good), b"x")
    session.add(
        PendingFileDeletion(
            storage_namespace="corrupt", next_attempt_at=datetime.now(UTC) - timedelta(minutes=1)
        )
    )
    session.add(PendingFileDeletion(storage_namespace=good.hex, next_attempt_at=datetime.now(UTC)))
    await session.commit()
    report = await run_file_cleanup(session_factory, storage)
    assert (report.removed, report.failed) == (1, 1)
    assert [r.storage_namespace for r in await pending_rows(session)] == ["corrupt"]


async def test_a_permanently_failing_record_stays_visible_and_is_logged_as_an_error(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session.add(PendingFileDeletion(storage_namespace="corrupt", next_attempt_at=datetime.now(UTC)))
    await session.commit()
    moment = datetime.now(UTC)
    with caplog.at_level(logging.WARNING):
        for _ in range(ESCALATE_AFTER_ATTEMPTS + 2):
            moment += timedelta(days=2)  # always due again
            await run_file_cleanup(session_factory, LocalStorage(tmp_path), now=moment)
    (record,) = await pending_rows(session)  # never silently dropped
    assert record.attempts == ESCALATE_AFTER_ATTEMPTS + 2
    assert record.next_attempt_at == moment + backoff_after(record.attempts)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    count, oldest = await pending_summary(session)  # what `python -m app.cleanup` reports
    assert count == 1 and oldest is not None


async def test_a_failed_database_deletion_creates_no_record_and_keeps_the_account(
    client: httpx.AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = await register_and_login(client, "stays@example.com")

    async def broken_commit(self: AsyncSession) -> None:
        raise RuntimeError("database went away")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", broken_commit)
        response = await client.post(
            DELETE, headers=bearer(tokens["access_token"]), json={"password": DEFAULT_PASSWORD}
        )
    assert response.status_code == 500
    assert await pending_rows(session) == []  # the to-do record rolled back with the deletion
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 1


def test_backoff_doubles_and_is_capped() -> None:
    assert [backoff_after(n) for n in (1, 2, 3, 4)] == [timedelta(minutes=m) for m in (1, 2, 4, 8)]
    assert backoff_after(50) == MAX_BACKOFF
    assert backoff_after(0) == timedelta(minutes=1)


async def test_the_summary_reports_the_backlog(
    session: AsyncSession,
) -> None:
    assert await pending_summary(session) == (0, None)
    session.add(PendingFileDeletion(storage_namespace=uuid.uuid4().hex))
    await session.commit()
    count, oldest = await pending_summary(session)
    assert count == 1 and oldest is not None


# --------------------------------------------------------- background loop & entry points


async def test_the_background_loop_retries_and_survives_errors(
    concurrent_engine: AsyncEngine, tmp_path: Path
) -> None:
    loop_factory = create_session_factory(concurrent_engine)  # the loop's own connections
    test_factory = create_session_factory(concurrent_engine)  # the test's own connection
    storage = FlakyStorage(tmp_path)
    owner = uuid.uuid4()
    await storage.put(new_storage_key(owner), b"x")
    async with test_factory() as db:
        db.add(PendingFileDeletion(storage_namespace=owner.hex, next_attempt_at=datetime.now(UTC)))
        await db.commit()

    task = asyncio.create_task(cleanup_loop(loop_factory, storage, 0.05))
    await asyncio.sleep(0.3)  # the first round fails (storage unhealthy) but the loop lives on
    assert not task.done()
    assert storage.calls >= 1
    storage.healthy = True
    async with test_factory() as db:  # pull the backoff forward so the next round is due
        await db.execute(update(PendingFileDeletion).values(next_attempt_at=datetime.now(UTC)))
        await db.commit()
    for _ in range(60):
        await asyncio.sleep(0.05)
        async with test_factory() as db:
            if not await pending_rows(db):
                break
    task.cancel()  # shutdown
    with pytest.raises(asyncio.CancelledError):
        await task
    async with test_factory() as db:
        assert await pending_rows(db) == []
    assert not (tmp_path / owner.hex).exists()


async def test_the_loop_survives_the_database_being_unavailable(tmp_path: Path) -> None:
    class BrokenFactory:
        calls = 0

        def __call__(self) -> AsyncSession:
            BrokenFactory.calls += 1
            raise ConnectionError("database is down")

    task = asyncio.create_task(
        cleanup_loop(BrokenFactory(), LocalStorage(tmp_path), 0.02)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.15)
    assert not task.done() and BrokenFactory.calls >= 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_application_runs_the_loop_while_it_is_up_and_stops_it_on_shutdown(
    app: FastAPI,
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    owner = uuid.uuid4()
    await storage.put(new_storage_key(owner), b"x")
    app.state.storage = storage
    app.state.file_cleanup_interval = 0.05
    session.add(PendingFileDeletion(storage_namespace=owner.hex, next_attempt_at=datetime.now(UTC)))
    await session.commit()

    async with app.router.lifespan_context(app):
        for _ in range(40):
            await asyncio.sleep(0.05)
            if not await pending_rows(session):
                break
        assert await pending_rows(session) == []
    assert not (tmp_path / "storage" / owner.hex).exists()


async def test_the_loop_can_be_switched_off(app: FastAPI) -> None:
    app.state.file_cleanup_interval = 0
    before = len(asyncio.all_tasks())
    async with app.router.lifespan_context(app):
        assert len(asyncio.all_tasks()) == before


async def test_the_command_line_entry_point_reports_and_sets_the_exit_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_file = tmp_path / "cli.db"
    engine: AsyncEngine = create_db_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    storage = LocalStorage(tmp_path / "storage")
    owner = uuid.uuid4()
    await storage.put(new_storage_key(owner), b"x")
    factory = create_session_factory(engine)
    async with factory() as db:
        db.add(PendingFileDeletion(storage_namespace=owner.hex, next_attempt_at=datetime.now(UTC)))
        await db.commit()
    await engine.dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "storage"))
    get_settings.cache_clear()
    try:
        assert await run_cli() == 0
    finally:
        get_settings.cache_clear()
    output = capsys.readouterr().out
    assert "removed=1" in output and "still_pending=0" in output
    assert not (tmp_path / "storage" / owner.hex).exists()
