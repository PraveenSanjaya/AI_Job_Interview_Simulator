"""Database behaviour of interview tables."""

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InterviewAnswer,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
    JobDescription,
    User,
    UserProfile,
)
from app.models.enums import EvaluationStatus, InterviewStatus, SessionDifficulty

pytestmark = pytest.mark.anyio


async def count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def seed(session: AsyncSession) -> tuple[User, InterviewSession, InterviewQuestion]:
    user = User(email="a@example.com", hashed_password="x", profile=UserProfile(full_name="Ada"))
    session.add(user)
    await session.flush()
    interview = InterviewSession(
        user_id=user.id,
        interview_types=["technical"],
        difficulty=SessionDifficulty.BEGINNER,
        question_count=3,
        max_followups=2,
        scoring_config={},
    )
    session.add(interview)
    await session.flush()
    question = InterviewQuestion(
        session_id=interview.id,
        user_id=user.id,
        main_index=0,
        category="technical",
        text="What is a list?",
        source="question_bank",
    )
    session.add(question)
    await session.flush()
    return user, interview, question


async def test_defaults(session: AsyncSession) -> None:
    _, interview, question = await seed(session)
    await session.commit()
    assert interview.status is InterviewStatus.CREATED
    assert interview.version == 0 and interview.current_index == 0
    assert interview.job_id is None and interview.started_at is None
    assert question.is_followup is False and question.asked_at is None


async def test_one_answer_per_question_and_one_evaluation_per_answer(
    session: AsyncSession,
) -> None:
    user, interview, question = await seed(session)
    answer = InterviewAnswer(
        question_id=question.id, session_id=interview.id, user_id=user.id, text="x"
    )
    session.add(answer)
    await session.flush()
    session.add(
        InterviewAnswer(question_id=question.id, session_id=interview.id, user_id=user.id, text="y")
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_question_positions_are_unique(session: AsyncSession) -> None:
    user, interview, _ = await seed(session)
    session.add(
        InterviewQuestion(
            session_id=interview.id,
            user_id=user.id,
            main_index=0,
            category="hr",
            text="Duplicate slot",
            source="question_bank",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_deleting_the_job_keeps_the_session(session: AsyncSession) -> None:
    user, interview, _ = await seed(session)
    job = JobDescription(
        user_id=user.id, title="T", description="d" * 50, description_sha256="0" * 64
    )
    session.add(job)
    await session.flush()
    interview.job_id = job.id
    interview.job_snapshot = {"title": "T"}
    await session.commit()

    await session.execute(delete(JobDescription))
    await session.commit()
    session.expire_all()
    kept = (await session.execute(select(InterviewSession))).scalar_one()
    assert kept.job_id is None and kept.job_snapshot == {"title": "T"}


async def test_deleting_a_user_removes_everything(session: AsyncSession) -> None:
    user, interview, question = await seed(session)
    answer = InterviewAnswer(
        question_id=question.id, session_id=interview.id, user_id=user.id, text="x"
    )
    session.add(answer)
    await session.flush()
    session.add_all(
        [
            InterviewEvaluation(
                answer_id=answer.id,
                session_id=interview.id,
                user_id=user.id,
                status=EvaluationStatus.UNAVAILABLE,
            ),
            InterviewReport(session_id=interview.id, user_id=user.id, result={}),
        ]
    )
    await session.commit()

    await session.execute(delete(User))  # plain SQL: relies on ON DELETE CASCADE
    await session.commit()
    for model in (
        InterviewSession,
        InterviewQuestion,
        InterviewAnswer,
        InterviewEvaluation,
        InterviewReport,
    ):
        assert await count(session, model) == 0
