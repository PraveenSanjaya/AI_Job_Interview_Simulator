"""Data access for resumes.

Every lookup is scoped by ``user_id``: a resume that belongs to someone else is
indistinguishable from one that does not exist.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume


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
