from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Certification,
    Education,
    Project,
    RefreshToken,
    Skill,
    User,
    UserProfile,
    WorkExperience,
)
from app.models.enums import ExperienceLevel, SkillCategory, UserRole

pytestmark = pytest.mark.anyio


def make_user(email: str = "a@example.com") -> User:
    return User(
        email=email,
        hashed_password="not-a-real-hash",  # noqa: S106
        profile=UserProfile(full_name="Ada Lovelace"),
    )


async def count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_user_defaults_and_profile_relationship(session: AsyncSession) -> None:
    session.add(make_user())
    await session.commit()
    user = (await session.execute(select(User))).scalar_one()
    assert user.role is UserRole.USER
    assert user.is_active is True
    assert user.id is not None
    assert user.created_at.tzinfo is not None
    assert user.profile.full_name == "Ada Lovelace"
    assert user.profile.user_id == user.id
    assert user.profile.preferred_roles == []


async def test_email_must_be_unique(session: AsyncSession) -> None:
    session.add(make_user("dup@example.com"))
    await session.commit()
    session.add(make_user("dup@example.com"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_profile_children_persist_in_order(session: AsyncSession) -> None:
    user = make_user()
    user.profile.experience_level = ExperienceLevel.JUNIOR
    user.profile.preferred_roles = ["Backend Developer", "Data Engineer"]
    user.profile.education = [
        Education(institution="SLIIT", degree="BSc IT", position=0, start_date=date(2022, 1, 1))
    ]
    user.profile.work_experience = [
        WorkExperience(company="Acme", title="Intern", position=0, is_current=True)
    ]
    user.profile.skills = [
        Skill(name="Python", category=SkillCategory.TECHNICAL, position=1),
        Skill(name="Teamwork", category=SkillCategory.SOFT, position=0),
    ]
    user.profile.projects = [Project(name="Sim", technologies=["fastapi"], position=0)]
    user.profile.certifications = [Certification(name="AWS CCP", position=0)]
    session.add(user)
    await session.commit()
    session.expunge_all()

    loaded = (await session.execute(select(User))).scalar_one()
    assert loaded.profile.experience_level is ExperienceLevel.JUNIOR
    assert loaded.profile.preferred_roles == ["Backend Developer", "Data Engineer"]
    assert [s.name for s in loaded.profile.skills] == ["Teamwork", "Python"]
    assert loaded.profile.projects[0].technologies == ["fastapi"]
    assert loaded.profile.education[0].start_date == date(2022, 1, 1)
    assert loaded.profile.work_experience[0].is_current is True


async def test_skill_unique_per_profile_and_category(session: AsyncSession) -> None:
    user = make_user()
    user.profile.skills = [
        Skill(name="Python", category=SkillCategory.TECHNICAL),
        Skill(name="Python", category=SkillCategory.TECHNICAL),
    ]
    session.add(user)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_user_cascades_to_all_owned_rows(session: AsyncSession) -> None:
    user = make_user()
    user.profile.skills = [Skill(name="Python", category=SkillCategory.TECHNICAL)]
    user.profile.education = [Education(institution="X", degree="Y")]
    session.add(user)
    await session.flush()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=user.id,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await session.commit()

    await session.delete(user)
    await session.commit()

    for model in (User, UserProfile, Skill, Education, RefreshToken):
        assert await count(session, model) == 0


async def test_database_level_cascade_without_orm(session: AsyncSession) -> None:
    """Foreign keys must cascade even when rows are deleted with plain SQL."""
    user = make_user()
    user.profile.skills = [Skill(name="Go", category=SkillCategory.TECHNICAL)]
    session.add(user)
    await session.commit()

    await session.execute(User.__table__.delete())  # type: ignore[attr-defined]
    await session.commit()
    assert await count(session, Skill) == 0
    assert await count(session, UserProfile) == 0


async def test_refresh_token_hash_is_unique(session: AsyncSession) -> None:
    user = make_user()
    session.add(user)
    await session.flush()
    expires = datetime.now(UTC) + timedelta(days=1)
    for _ in range(2):
        session.add(
            RefreshToken(
                user_id=user.id, family_id=user.id, token_hash="b" * 64, expires_at=expires
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()
