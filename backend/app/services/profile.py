"""Candidate profile business logic."""

from collections.abc import Callable
from typing import Any

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
from app.schemas.profile import (
    ApplyMode,
    ApplyToProfileRequest,
    ProfileResponse,
    ProfileUpdate,
    SkippedField,
)


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

    async def apply_selected(
        self, user: User, data: ApplyToProfileRequest
    ) -> tuple[UserProfile, dict[str, int], list[SkippedField]]:
        """Apply user-reviewed data without discarding what the profile already holds.

        * Scalars: filled when empty; a different existing value is kept (and reported
          as skipped) unless ``overwrite_existing`` is set.
        * Lists in ``merge`` mode: new items are appended, duplicates are skipped and
          existing items are never modified or removed. In ``replace`` mode the user
          has explicitly chosen to replace that whole section.
        """
        profile = await self.get(user)
        applied: dict[str, int] = {}
        skipped: list[SkippedField] = []

        for field in ("full_name", "headline", "career_objective"):
            new = getattr(data, field)
            if new is None:
                continue
            existing = getattr(profile, field)
            if existing and existing != new and not data.overwrite_existing:
                skipped.append(
                    SkippedField(field=field, reason="profile already has a different value")
                )
            elif existing != new:
                setattr(profile, field, new)
                applied[field] = 1

        sections: dict[
            str, tuple[type[Any], list[Any] | None, Callable[[Any], tuple[Any, ...]]]
        ] = {
            "education": (Education, data.education, lambda e: (e.institution, e.degree)),
            "work_experience": (
                WorkExperience,
                data.work_experience,
                lambda w: (w.company, w.title, w.start_date),
            ),
            "skills": (Skill, data.skills, lambda s: (s.category, s.name)),
            "projects": (Project, data.projects, lambda p: (p.name,)),
            "certifications": (Certification, data.certifications, lambda c: (c.name, c.issuer)),
        }
        for name, (model, items, key) in sections.items():
            if items is None:
                continue
            current: list[Any] = getattr(profile, name)
            if data.mode is ApplyMode.REPLACE:
                setattr(profile, name, [])
                await self._session.flush()  # delete before insert (unique constraints)
                current = getattr(profile, name)
                existing_keys: set[tuple[Any, ...]] = set()
            else:
                existing_keys = {_fold(key(row)) for row in current}
            added = 0
            for item in items:
                if _fold(key(item)) in existing_keys:
                    continue
                existing_keys.add(_fold(key(item)))
                current.append(model(position=len(current), **item.model_dump()))
                added += 1
            duplicates = len(items) - added
            if added:
                applied[name] = added
            if duplicates and data.mode is ApplyMode.MERGE:
                skipped.append(SkippedField(field=name, reason=f"{duplicates} already present"))
        await self._session.commit()
        return profile, applied, skipped

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


def _fold(parts: tuple[Any, ...]) -> tuple[Any, ...]:
    """Case-insensitive comparison key for duplicate detection."""
    return tuple(p.casefold() if isinstance(p, str) else p for p in parts)
