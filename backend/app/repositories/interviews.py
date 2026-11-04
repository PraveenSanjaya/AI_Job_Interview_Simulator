"""Data access for interviews. Every lookup is scoped by ``user_id``."""

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InterviewAnswer,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
)
from app.models.enums import InterviewStatus


class InterviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ----------------------------------------------------------------- sessions

    def add_session(self, interview: InterviewSession) -> None:
        self._session.add(interview)

    async def get_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> InterviewSession | None:
        result = await self._session.execute(
            select(InterviewSession)
            .where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_sessions(self, user_id: uuid.UUID) -> list[InterviewSession]:
        result = await self._session.execute(
            select(InterviewSession)
            .where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.created_at.desc(), InterviewSession.id)
        )
        return list(result.scalars())

    async def transition(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        allowed_from: Iterable[InterviewStatus],
        to: InterviewStatus,
        values: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically move a session to ``to`` if it is currently in ``allowed_from``."""
        result = await self._session.execute(
            update(InterviewSession)
            .where(
                InterviewSession.id == session_id,
                InterviewSession.user_id == user_id,
                InterviewSession.status.in_(list(allowed_from)),
            )
            .values(status=to, **(values or {}))
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]

    async def claim_answer_slot(
        self, user_id: uuid.UUID, session_id: uuid.UUID, expected_version: int, now: datetime
    ) -> bool:
        """Accept one answer for a running session at ``expected_version``. Of several
        concurrent submissions based on the same version exactly one succeeds."""
        result = await self._session.execute(
            update(InterviewSession)
            .where(
                InterviewSession.id == session_id,
                InterviewSession.user_id == user_id,
                InterviewSession.status == InterviewStatus.IN_PROGRESS,
                InterviewSession.version == expected_version,
            )
            .values(version=expected_version + 1, last_activity_at=now)
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]

    # ---------------------------------------------------------------- questions

    def add_questions(self, questions: Iterable[InterviewQuestion]) -> None:
        self._session.add_all(list(questions))

    async def list_questions(self, session_id: uuid.UUID) -> list[InterviewQuestion]:
        result = await self._session.execute(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.main_index, InterviewQuestion.followup_index)
        )
        return list(result.scalars())

    async def get_question(
        self, session_id: uuid.UUID, question_id: uuid.UUID
    ) -> InterviewQuestion | None:
        result = await self._session.execute(
            select(InterviewQuestion).where(
                InterviewQuestion.id == question_id, InterviewQuestion.session_id == session_id
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------ answers & evaluations

    def add_answer(self, answer: InterviewAnswer) -> None:
        self._session.add(answer)

    def add_evaluation(self, evaluation: InterviewEvaluation) -> None:
        self._session.add(evaluation)

    async def list_answers(self, session_id: uuid.UUID) -> list[InterviewAnswer]:
        result = await self._session.execute(
            select(InterviewAnswer)
            .where(InterviewAnswer.session_id == session_id)
            .order_by(InterviewAnswer.submitted_at, InterviewAnswer.id)
        )
        return list(result.scalars())

    async def list_evaluations(self, session_id: uuid.UUID) -> list[InterviewEvaluation]:
        result = await self._session.execute(
            select(InterviewEvaluation)
            .where(InterviewEvaluation.session_id == session_id)
            .order_by(InterviewEvaluation.created_at, InterviewEvaluation.id)
        )
        return list(result.scalars())

    # ------------------------------------------------------------------ reports

    def add_report(self, report: InterviewReport) -> None:
        self._session.add(report)

    async def get_report(self, user_id: uuid.UUID, session_id: uuid.UUID) -> InterviewReport | None:
        result = await self._session.execute(
            select(InterviewReport).where(
                InterviewReport.session_id == session_id, InterviewReport.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def latest_report(self, user_id: uuid.UUID) -> InterviewReport | None:
        result = await self._session.execute(
            select(InterviewReport)
            .where(InterviewReport.user_id == user_id)
            .order_by(InterviewReport.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def recent_question_texts(self, user_id: uuid.UUID, limit: int) -> list[str]:
        """Main questions the user was most recently asked (to avoid repeating them)."""
        result = await self._session.execute(
            select(InterviewQuestion.text)
            .where(InterviewQuestion.user_id == user_id, InterviewQuestion.asked_at.is_not(None))
            .order_by(InterviewQuestion.asked_at.desc())
            .limit(limit)
        )
        return list(result.scalars())
