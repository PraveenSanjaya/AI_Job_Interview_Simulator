"""Retryable removal of stored files that outlived their account.

When an account is deleted its database rows go in one transaction, together with a
``PendingFileDeletion`` record naming the user's storage namespace. The files are removed
right afterwards; if that fails, the record stays and ``run_file_cleanup`` retries it with
exponential backoff until it succeeds. Because the record has no link to the (now missing)
account, this works even though the account no longer exists.

Safe to run from several instances at once: removing a namespace is idempotent, and on
PostgreSQL ``FOR UPDATE SKIP LOCKED`` makes instances take different records.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import PendingFileDeletion
from app.storage.base import StorageBackend, StorageError

logger = logging.getLogger(__name__)

BASE_BACKOFF = timedelta(minutes=1)
MAX_BACKOFF = timedelta(hours=24)
BATCH_SIZE = 50
CLAIM_LEASE = timedelta(minutes=5)  # how long a worker owns a record it is processing
ESCALATE_AFTER_ATTEMPTS = 5  # from here on every failure is logged as an error


@dataclass
class CleanupReport:
    attempted: int = 0
    removed: int = 0
    failed: int = 0


def backoff_after(attempts: int) -> timedelta:
    """1 min, 2, 4, ... capped at 24 h, after the n-th failed attempt."""
    factor: int = 2 ** min(max(attempts - 1, 0), 20)
    return min(BASE_BACKOFF * factor, MAX_BACKOFF)


async def try_remove(
    session: AsyncSession,
    storage: StorageBackend,
    pending: PendingFileDeletion,
    now: datetime,
) -> bool:
    """Attempt one claimed record. Deletes it on success, schedules a retry on failure.

    Uses plain UPDATE/DELETE statements keyed by id (not ORM flushes), so a record that
    vanished meanwhile is not an error.
    """
    try:
        await storage.delete_namespace(uuid.UUID(hex=pending.storage_namespace))
    except (StorageError, ValueError):
        attempts = pending.attempts + 1
        await session.execute(
            update(PendingFileDeletion)
            .where(PendingFileDeletion.id == pending.id)
            .values(
                attempts=attempts,
                last_attempt_at=now,
                next_attempt_at=now + backoff_after(attempts),
            )
        )
        await session.commit()
        log = logger.error if attempts >= ESCALATE_AFTER_ATTEMPTS else logger.warning
        log(
            "Stored files of a deleted account could not be removed; will retry",
            extra={"storage_namespace": pending.storage_namespace, "attempts": attempts},
        )
        return False
    await session.execute(delete(PendingFileDeletion).where(PendingFileDeletion.id == pending.id))
    await session.commit()
    return True


async def claim(
    session: AsyncSession, pending_id: uuid.UUID, now: datetime
) -> PendingFileDeletion | None:
    """Atomically take a due record for this worker, or return None if someone else did.

    The claim is a conditional UPDATE that pushes ``next_attempt_at`` into the future (a
    lease). Only one UPDATE can match a row that is still due, on every database and
    across processes, so two workers never process the same record at the same time. If
    the worker dies mid-way the lease simply expires and the record becomes due again.
    """
    result = await session.execute(
        update(PendingFileDeletion)
        .where(PendingFileDeletion.id == pending_id, PendingFileDeletion.next_attempt_at <= now)
        .values(next_attempt_at=now + CLAIM_LEASE)
    )
    await session.commit()
    if cast(CursorResult[Any], result).rowcount != 1:
        return None
    return (
        await session.execute(
            select(PendingFileDeletion)
            .where(PendingFileDeletion.id == pending_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def run_file_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageBackend,
    *,
    now: datetime | None = None,
) -> CleanupReport:
    """Retry every record that is due. Returns what happened; never raises on file errors."""
    moment = now or datetime.now(UTC)
    report = CleanupReport()
    async with session_factory() as listing:
        due = (
            (
                await listing.execute(
                    select(PendingFileDeletion.id)
                    .where(PendingFileDeletion.next_attempt_at <= moment)
                    .order_by(PendingFileDeletion.next_attempt_at)
                    .limit(BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
    for pending_id in due:
        async with session_factory() as session:
            pending = await claim(session, pending_id, moment)
            if pending is None:  # finished or claimed by another worker
                continue
            report.attempted += 1
            if await try_remove(session, storage, pending, moment):
                report.removed += 1
            else:
                report.failed += 1
    return report


async def pending_summary(session: AsyncSession) -> tuple[int, datetime | None]:
    """How many records wait, and when the oldest was created (for operators)."""
    rows = (await session.execute(select(PendingFileDeletion.created_at))).scalars().all()
    return len(rows), min(rows) if rows else None


async def cleanup_loop(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageBackend,
    interval_seconds: float,
) -> None:
    """Run the cleanup now and then every ``interval_seconds`` until cancelled."""
    while True:
        try:
            report = await run_file_cleanup(session_factory, storage)
            if report.attempted:
                logger.info(
                    "File cleanup finished",
                    extra={"removed": report.removed, "failed": report.failed},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # e.g. the database is briefly unreachable; the next round tries again.
            logger.warning("File cleanup round failed", exc_info=True)
        await asyncio.sleep(interval_seconds)
