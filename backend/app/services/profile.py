"""Candidate profile business logic."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Certification,
    Education,
    Project,
    Skill,
    User,
    UserProfile,
    WorkExperience,
)
from app.repositories.profiles import ProfileRepository
from app.schemas.profile import ProfileResponse, ProfileUpdate


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._profiles = ProfileRepository(session)

    async def get(self, user: User) -> UserProfile:
        profile = await self._profiles.get_by_user_id(user.id)
        if profile is None:
            # Registration always creates a profile; this repairs legacy/partial data.
            profile = UserProfile(user_id=user.id, full_name=user.email)
            self._profiles.add(profile)
            await self._session.commit()
        return profile

    async def replace(self, user: User, data: ProfileUpdate) -> UserProfile:
        profile = await self.get(user)

        profile.full_name = data.full_name
        profile.headline = data.headline
        profile.career_objective = data.career_objective
        profile.experience_level = data.experience_level
        profile.preferred_difficulty = data.preferred_difficulty
        profile.preferred_roles = list(data.preferred_roles)

        # Remove the old children and flush first: SQLAlchemy emits INSERTs before
        # DELETEs, which would violate the (profile, category, name) unique constraint
        # when a skill is re-submitted unchanged.
        profile.education = []
        profile.work_experience = []
        profile.skills = []
        profile.projects = []
        profile.certifications = []
        await self._session.flush()

        profile.education = [
            Education(position=i, **item.model_dump()) for i, item in enumerate(data.education)
        ]
        profile.work_experience = [
            WorkExperience(position=i, **item.model_dump())
            for i, item in enumerate(data.work_experience)
        ]
        profile.skills = [
            Skill(position=i, **item.model_dump()) for i, item in enumerate(data.skills)
        ]
        profile.projects = [
            Project(position=i, **item.model_dump()) for i, item in enumerate(data.projects)
        ]
        profile.certifications = [
            Certification(position=i, **item.model_dump())
            for i, item in enumerate(data.certifications)
        ]
        await self._session.commit()
        return profile

    @staticmethod
    def to_response(user: User, profile: UserProfile) -> ProfileResponse:
        return ProfileResponse.model_validate(
            {**{f: getattr(profile, f) for f in _PROFILE_FIELDS}, "email": user.email},
            from_attributes=True,
        )


_PROFILE_FIELDS = (
    "full_name",
    "headline",
    "career_objective",
    "experience_level",
    "preferred_difficulty",
    "preferred_roles",
    "education",
    "work_experience",
    "skills",
    "projects",
    "certifications",
    "updated_at",
)
