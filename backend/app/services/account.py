"""Account deletion: remove a user and everything they own."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.core.passwords import verify_password
from app.models import PendingFileDeletion, User
from app.services.file_cleanup import backoff_after
from app.storage.base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        self._session = session
        self._storage = storage

    async def delete_account(self, user: User, password: str) -> bool:
        """Permanently delete ``user``. Returns whether every stored file was removed.

        Order matters for safety:

        1. The password is checked again, so a stolen access token alone cannot erase an
           account.
        2. The database row is deleted in one transaction. Every table that holds user data
           references ``users.id`` with ``ON DELETE CASCADE`` (profile and its sections,
           refresh tokens, resumes and analyses, integration sources and analyses, jobs,
           analyses and matches, interviews with their questions, answers, evaluations and
           reports), so the records vanish together or not at all. Deleting only this
           user's id cannot touch anyone else's rows.
        3. Only after that commit are the uploaded files removed. If this step fails the
           account is already gone and the files are unreachable, so the failure is
           reported (and logged) instead of being hidden or undoing the deletion.

        Removing files first would be worse: a failed database step would leave an
        account whose uploads were already destroyed.
        """
        valid = await asyncio.to_thread(verify_password, password, user.hashed_password)
        if not valid:
            raise ForbiddenError("The password is incorrect", code="incorrect_password")

        user_id = user.id
        now = datetime.now(UTC)
        pending = PendingFileDeletion(
            storage_namespace=user_id.hex, next_attempt_at=now, attempts=0
        )
        try:
            # The to-do record is part of the same transaction as the deletion, so either
            # both happen or neither does: the intent to clean up cannot be lost.
            self._session.add(pending)
            await self._session.execute(delete(User).where(User.id == user_id))
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        try:
            await self._storage.delete_namespace(user_id)
        except StorageError:
            # Keep the record: the sweeper (app.services.file_cleanup) retries with backoff.
            pending.attempts = 1
            pending.last_attempt_at = now
            pending.next_attempt_at = now + backoff_after(1)
            await self._session.commit()
            logger.error(
                "Account deleted but some stored files could not be removed; will retry",
                extra={"storage_namespace": user_id.hex},
            )
            return False
        await self._session.delete(pending)
        await self._session.commit()
        return True
