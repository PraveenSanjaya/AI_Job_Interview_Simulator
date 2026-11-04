"""Data access for job descriptions, analyses and matches (always scoped by user)."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobAnalysis, JobDescription, JobMatch


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ descriptions

    def add_job(self, job: JobDescription) -> None:
        self._session.add(job)

    async def get_job(self, user_id: uuid.UUID, job_id: uuid.UUID) -> JobDescription | None:
        result = await self._session.execute(
            select(JobDescription).where(
                JobDescription.id == job_id, JobDescription.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_jobs(self, user_id: uuid.UUID) -> list[JobDescription]:
        result = await self._session.execute(
            select(JobDescription)
            .where(JobDescription.user_id == user_id)
            .order_by(JobDescription.created_at.desc(), JobDescription.id)
        )
        return list(result.scalars())

    async def delete_job(self, user_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Deleting a job also deletes its analysis and match reports (ON DELETE CASCADE)."""
        result = await self._session.execute(
            delete(JobDescription).where(
                JobDescription.id == job_id, JobDescription.user_id == user_id
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    # ---------------------------------------------------------------- analysis

    async def get_analysis(self, user_id: uuid.UUID, job_id: uuid.UUID) -> JobAnalysis | None:
        result = await self._session.execute(
            select(JobAnalysis).where(JobAnalysis.job_id == job_id, JobAnalysis.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def replace_analysis(self, analysis: JobAnalysis) -> None:
        """Store ``analysis`` as the job's only current analysis. The caller commits."""
        await self._session.execute(
            delete(JobAnalysis).where(
                JobAnalysis.job_id == analysis.job_id, JobAnalysis.user_id == analysis.user_id
            )
        )
        self._session.add(analysis)
        await self._session.flush()

    async def delete_analysis(self, user_id: uuid.UUID, job_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(JobAnalysis).where(JobAnalysis.job_id == job_id, JobAnalysis.user_id == user_id)
        )

    # ----------------------------------------------------------------- matches

    def add_match(self, match: JobMatch) -> None:
        self._session.add(match)

    async def get_match(
        self, user_id: uuid.UUID, job_id: uuid.UUID, match_id: uuid.UUID
    ) -> JobMatch | None:
        result = await self._session.execute(
            select(JobMatch).where(
                JobMatch.id == match_id, JobMatch.job_id == job_id, JobMatch.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_matches(self, user_id: uuid.UUID, job_id: uuid.UUID) -> list[JobMatch]:
        result = await self._session.execute(
            select(JobMatch)
            .where(JobMatch.job_id == job_id, JobMatch.user_id == user_id)
            .order_by(JobMatch.created_at.desc(), JobMatch.id)
        )
        return list(result.scalars())
