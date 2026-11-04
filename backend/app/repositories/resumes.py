"""Data access for resumes.

Every lookup is scoped by ``user_id``: a resume that belongs to someone else is
indistinguishable from one that does not exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume
from app.models.enums import FailureStage, ResumeStatus


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, resume: Resume) -> None:
        self._session.add(resume)

    async def get_for_user(self, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume | None:
        result = await self._session.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Resume]:
        result = await self._session.execute(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
        )
        return list(result.scalars())

    async def delete(self, resume: Resume) -> None:
        await self._session.delete(resume)

    async def claim_for_analysis(
        self, resume_id: uuid.UUID, user_id: uuid.UUID, now: datetime, stale_before: datetime
    ) -> bool:
        """Atomically move a resume to ``analyzing`` if it is allowed to be analysed.

        Allowed: extracted, completed (re-analysis), failed during a previous analysis,
        or stuck in ``analyzing`` since before ``stale_before`` (e.g. a crashed worker).
        The conditional UPDATE ensures two concurrent requests cannot both start.
        """
        runnable = or_(
            Resume.status.in_([ResumeStatus.EXTRACTED, ResumeStatus.COMPLETED]),
            and_(
                Resume.status == ResumeStatus.FAILED,
                Resume.failure_stage == FailureStage.ANALYSIS,
            ),
            and_(Resume.status == ResumeStatus.ANALYZING, Resume.updated_at < stale_before),
        )
        result = await self._session.execute(
            update(Resume)
            .where(Resume.id == resume_id, Resume.user_id == user_id, runnable)
            .values(
                status=ResumeStatus.ANALYZING,
                failure_stage=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]
