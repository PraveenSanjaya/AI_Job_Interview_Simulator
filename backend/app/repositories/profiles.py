"""Data access for candidate profiles.

Every lookup is keyed by the *authenticated* user's id; callers never pass a
client-supplied profile id, so one user cannot address another user's profile.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserProfile | None:
        result = await self._session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def add(self, profile: UserProfile) -> None:
        self._session.add(profile)
