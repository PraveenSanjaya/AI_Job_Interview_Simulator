"""Database behaviour of job descriptions, analyses and match reports."""

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobAnalysis, JobDescription, JobMatch, User, UserProfile
from app.models.enums import JobStatus

pytestmark = pytest.mark.anyio


async def count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def make_user(session: AsyncSession, email: str = "a@example.com") -> User:
    user = User(email=email, hashed_password="x", profile=UserProfile(full_name="Ada"))
    session.add(user)
    await session.flush()
    return user


def make_job(user: User, title: str = "Backend Engineer") -> JobDescription:
    return JobDescription(
        user_id=user.id, title=title, description="We need Python.", description_sha256="a" * 64
    )


def make_analysis(job: JobDescription) -> JobAnalysis:
    return JobAnalysis(
        job_id=job.id,
        user_id=job.user_id,
        parser="deterministic",
        description_sha256=job.description_sha256,
        result={},
    )


def make_match(job: JobDescription) -> JobMatch:
    return JobMatch(
        job_id=job.id,
        user_id=job.user_id,
        overall_score=70,
        confidence="medium",
        scoring_config={},
        evidence_used={},
        result={},
    )


async def test_job_defaults(session: AsyncSession) -> None:
    user = await make_user(session)
    job = make_job(user)
    session.add(job)
    await session.commit()
    stored = (await session.execute(select(JobDescription))).scalar_one()
    assert stored.status is JobStatus.SAVED
    assert stored.company is None
    assert stored.source_url is None
    assert stored.created_at.tzinfo is not None


async def test_only_one_current_analysis_per_job(session: AsyncSession) -> None:
    user = await make_user(session)
    job = make_job(user)
    session.add(job)
    await session.flush()
    session.add_all([make_analysis(job), make_analysis(job)])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_deleting_a_job_removes_its_analysis_and_matches(session: AsyncSession) -> None:
    user = await make_user(session)
    job = make_job(user)
    session.add(job)
    await session.flush()
    session.add_all([make_analysis(job), make_match(job), make_match(job)])
    await session.commit()

    await session.execute(delete(JobDescription))  # plain SQL: relies on ON DELETE CASCADE
    await session.commit()
    assert await count(session, JobAnalysis) == 0
    assert await count(session, JobMatch) == 0


async def test_deleting_a_user_removes_all_job_data(session: AsyncSession) -> None:
    user = await make_user(session)
    job = make_job(user)
    session.add(job)
    await session.flush()
    session.add_all([make_analysis(job), make_match(job)])
    await session.commit()

    await session.execute(delete(User))
    await session.commit()
    for model in (JobDescription, JobAnalysis, JobMatch):
        assert await count(session, model) == 0


async def test_matches_survive_deleting_the_analysis(session: AsyncSession) -> None:
    """Match reports are historical records and hold no link to the analysis."""
    user = await make_user(session)
    job = make_job(user)
    session.add(job)
    await session.flush()
    session.add_all([make_analysis(job), make_match(job)])
    await session.commit()

    await session.execute(delete(JobAnalysis))
    await session.commit()
    assert await count(session, JobMatch) == 1
