"""Mock interviews: configure, run (question, answer, follow-up), evaluate and report."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.ai.base import LLMProvider
from app.api.deps import (
    CurrentUserDep,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
    get_llm_provider,
)
from app.interview.config import InterviewScoringConfig
from app.interview.schemas import EvaluationResult, InterviewReportData
from app.models import (
    InterviewAnswer,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewSession,
)
from app.schemas.interviews import (
    AnswerCreate,
    AnswerSubmitted,
    AnswerView,
    CurrentQuestionResponse,
    EvaluationResponse,
    InterviewCreate,
    InterviewResponse,
    QuestionResponse,
    ReportResponse,
    SessionSummary,
)
from app.services.interviews import InterviewService

router = APIRouter(prefix="/interviews", tags=["interviews"])


def get_interview_service(
    session: SessionDep,
    settings: SettingsDep,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> InterviewService:
    return InterviewService(session, settings, provider)


ServiceDep = Annotated[InterviewService, Depends(get_interview_service)]

_AI_NOTES = {
    "disabled_by_user": "AI was turned off for this interview; the question bank is used.",
    "provider_unavailable": "No AI provider is configured; the question bank is used and "
    "answers are saved without evaluation.",
    "consent_not_given": "The AI provider is external and you did not allow external AI "
    "(allow_external_ai); nothing was sent and the question bank is used.",
}


def _notes(interview: InterviewSession) -> list[str]:
    notes: list[str] = []
    if interview.mode == "question_bank":
        status_text = interview.ai_status or ""
        if status_text.startswith("generation_failed"):
            notes.append(
                "AI question generation failed, so the question bank is used and answers "
                "are saved without evaluation."
            )
        else:
            notes.append(_AI_NOTES.get(status_text, "The question bank is used."))
        notes.append("Adaptive follow-ups and answer evaluation are unavailable.")
    return notes


def question_response(
    question: InterviewQuestion, answer: InterviewAnswer | None = None
) -> QuestionResponse:
    return QuestionResponse(
        id=question.id,
        main_index=question.main_index,
        followup_index=question.followup_index,
        is_followup=question.is_followup,
        followup_kind=question.followup_kind,
        category=question.category,
        text=question.text,
        source=question.source,
        skill_tags=list(question.skill_tags),
        asked_at=question.asked_at,
        answer=answer_view(answer) if answer else None,
    )


def answer_view(answer: InterviewAnswer) -> AnswerView:
    return AnswerView(
        id=answer.id, text=answer.text, skipped=answer.skipped, submitted_at=answer.submitted_at
    )


def evaluation_response(
    evaluation: InterviewEvaluation, question_id: uuid.UUID
) -> EvaluationResponse:
    return EvaluationResponse(
        id=evaluation.id,
        answer_id=evaluation.answer_id,
        question_id=question_id,
        status=evaluation.status,
        reason=evaluation.reason,
        provider=evaluation.provider,
        model=evaluation.model,
        result=EvaluationResult.model_validate(evaluation.result) if evaluation.result else None,
        created_at=evaluation.created_at,
    )


async def interview_response(
    service: InterviewService, interview: InterviewSession
) -> InterviewResponse:
    return InterviewResponse(
        id=interview.id,
        status=interview.status,
        interview_types=list(interview.interview_types),
        difficulty=interview.difficulty,
        question_count=interview.question_count,
        max_followups=interview.max_followups,
        job_id=interview.job_id,
        job_title=(interview.job_snapshot or {}).get("title"),
        use_ai=interview.use_ai,
        consent_external_ai=interview.consent_external_ai,
        mode=interview.mode,
        ai_status=interview.ai_status,
        adaptive_followups=None if interview.mode is None else interview.mode == "ai",
        notes=_notes(interview),
        ai_provider=interview.ai_provider,
        ai_model=interview.ai_model,
        scoring_config=InterviewScoringConfig.model_validate(interview.scoring_config),
        progress=await service.progress(interview),
        created_at=interview.created_at,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        last_activity_at=interview.last_activity_at,
    )


# ------------------------------------------------------------------- sessions


@router.post("", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_interview(
    body: InterviewCreate, user: CurrentUserDep, service: ServiceDep
) -> InterviewResponse:
    """Configure a mock interview (types, difficulty, length, optional job). No questions
    are generated until it is started. With no AI provider the curated question bank is
    used and answers are saved without evaluation."""
    return await interview_response(service, await service.create(user, body))


@router.get("", response_model=list[SessionSummary])
async def list_interviews(user: CurrentUserDep, service: ServiceDep) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=i.id,
            status=i.status,
            interview_types=list(i.interview_types),
            difficulty=i.difficulty,
            job_title=(i.job_snapshot or {}).get("title"),
            mode=i.mode,
            created_at=i.created_at,
            completed_at=i.completed_at,
        )
        for i in await service.list_all(user)
    ]


@router.get("/{session_id}", response_model=InterviewResponse)
async def get_interview(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> InterviewResponse:
    return await interview_response(service, await service.get(user, session_id))


@router.post("/{session_id}/start", response_model=InterviewResponse)
async def start_interview(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep, limiter: RateLimiterDep
) -> InterviewResponse:
    """Start a created interview (generating its questions) or resume an interrupted one.

    ``409 invalid_interview_state`` if it is completed, cancelled, expired or already running."""
    await limiter.hit(f"interview:user:{user.id}")
    return await interview_response(service, await service.start(user, session_id))


@router.post("/{session_id}/cancel", response_model=InterviewResponse)
async def cancel_interview(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> InterviewResponse:
    return await interview_response(service, await service.cancel(user, session_id))


@router.post("/{session_id}/complete", response_model=ReportResponse)
async def complete_interview(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep, limiter: RateLimiterDep
) -> ReportResponse:
    """Finish the interview (also early) and get the report. Questions never asked are left
    out of the score."""
    await limiter.hit(f"interview:user:{user.id}")
    report = await service.complete(user, session_id)
    return _report_response(report.id, report.session_id, report.created_at, report.overall_score,
                            report.result)  # fmt: skip


# ----------------------------------------------------------- questions & answers


@router.get("/{session_id}/current-question", response_model=CurrentQuestionResponse)
async def current_question(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> CurrentQuestionResponse:
    interview, question, all_done = await service.current(user, session_id)
    return CurrentQuestionResponse(
        status=interview.status,
        question=question_response(question) if question else None,
        all_questions_answered=all_done,
    )


@router.get("/{session_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> list[QuestionResponse]:
    """Questions asked so far with your answers. Later questions stay hidden."""
    _, pairs = await service.questions(user, session_id)
    return [question_response(q, a) for q, a in pairs]


@router.post(
    "/{session_id}/answers", response_model=AnswerSubmitted, status_code=status.HTTP_201_CREATED
)
async def submit_answer(
    session_id: uuid.UUID,
    body: AnswerCreate,
    user: CurrentUserDep,
    service: ServiceDep,
    limiter: RateLimiterDep,
) -> AnswerSubmitted:
    """Answer (or skip) the current question.

    The answer is always saved. When AI is in use it is evaluated and a follow-up may be
    asked (up to ``max_followups`` per question); otherwise its evaluation is reported as
    ``unavailable`` and no follow-up is asked. Errors: ``409 not_current_question``,
    ``409 concurrent_submission``, ``409 invalid_interview_state``.
    """
    await limiter.hit(f"interview-answer:user:{user.id}")
    answer, evaluation, next_question, follow_up_asked, note = await service.answer(
        user, session_id, body
    )
    interview = await service.get(user, session_id)
    _, open_question, all_done = await service.current(user, session_id)
    return AnswerSubmitted(
        answer=answer_view(answer),
        evaluation=evaluation_response(evaluation, answer.question_id),
        follow_up_asked=follow_up_asked,
        followups_note=note,
        next_question=question_response(next_question) if next_question else None,
        all_questions_answered=all_done and open_question is None,
        progress=await service.progress(interview),
    )


# ------------------------------------------------------------ evaluation & report


@router.get("/{session_id}/evaluations", response_model=list[EvaluationResponse])
async def list_evaluations(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> list[EvaluationResponse]:
    """Evaluation of each answered question: scores, explanations and suggestions, or the
    reason there is none (``unavailable``, ``failed``, ``not_evaluated``)."""
    return [evaluation_response(e, qid) for e, qid in await service.evaluations(user, session_id)]


def _report_response(
    report_id: uuid.UUID,
    session_id: uuid.UUID,
    created_at: datetime,
    overall_score: int | None,
    result: dict[str, object],
) -> ReportResponse:
    return ReportResponse(
        id=report_id,
        session_id=session_id,
        created_at=created_at,
        overall_score=overall_score,
        report=InterviewReportData.model_validate(result),
    )


@router.get("/{session_id}/report", response_model=ReportResponse)
async def get_report(
    session_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep
) -> ReportResponse:
    """The stored report of a completed interview. ``409 report_not_ready`` before that."""
    report = await service.report(user, session_id)
    return _report_response(
        report.id, report.session_id, report.created_at, report.overall_score, report.result
    )
