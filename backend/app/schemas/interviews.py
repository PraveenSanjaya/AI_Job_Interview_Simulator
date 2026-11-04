"""Request/response models for mock interviews."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.interview.config import InterviewScoringConfig
from app.interview.schemas import EvaluationResult, InterviewReportData
from app.models.enums import EvaluationStatus, InterviewStatus, InterviewType, SessionDifficulty

MAX_ANSWER_CHARS = 8000

AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_ANSWER_CHARS)]


class InterviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interview_types: list[InterviewType] = Field(
        min_length=1,
        max_length=7,
        description="One or more of hr, behavioral, technical, programming, project, "
        "system_design, job_specific (job_specific needs a job_id).",
    )
    difficulty: SessionDifficulty
    question_count: int = Field(default=10, ge=1, le=100, description="Main questions (1-30).")
    job_id: uuid.UUID | None = Field(
        default=None, description="A saved job to tailor the interview to (optional)."
    )
    max_followups: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Follow-ups allowed per main question; defaults to the server setting.",
    )
    use_ai: bool = Field(
        default=True,
        description="Use the configured AI provider for questions, follow-ups, evaluation and "
        "feedback. Without one, the curated question bank is used and answers are saved "
        "unevaluated.",
    )
    allow_external_ai: bool = Field(
        default=False,
        description="Explicit consent, required when the provider is external, to send the "
        "interview context and your answers to it. Without it the question bank is used.",
    )
    scoring: dict[str, Any] | None = Field(
        default=None,
        description="Optional overrides of the scoring rules (weights, followup_weight, "
        "skipped_counts_as_zero, strong_threshold, weak_threshold).",
    )

    @model_validator(mode="after")
    def _unique_types(self) -> "InterviewCreate":
        if len(set(self.interview_types)) != len(self.interview_types):
            raise ValueError("interview_types must not repeat")
        return self


class Progress(BaseModel):
    main_questions_total: int
    main_questions_asked: int
    answered: int
    skipped: int
    followups_asked: int
    remaining_main_questions: int


class InterviewResponse(BaseModel):
    id: uuid.UUID
    status: InterviewStatus
    interview_types: list[str]
    difficulty: SessionDifficulty
    question_count: int
    max_followups: int
    job_id: uuid.UUID | None
    job_title: str | None
    use_ai: bool
    consent_external_ai: bool
    mode: str | None
    ai_status: str | None
    adaptive_followups: bool | None
    notes: list[str]
    ai_provider: str | None
    ai_model: str | None
    scoring_config: InterviewScoringConfig
    progress: Progress
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_activity_at: datetime


class AnswerView(BaseModel):
    id: uuid.UUID
    text: str | None
    skipped: bool
    submitted_at: datetime


class QuestionResponse(BaseModel):
    id: uuid.UUID
    main_index: int
    followup_index: int
    is_followup: bool
    followup_kind: str | None
    category: str
    text: str
    source: str
    skill_tags: list[str]
    asked_at: datetime | None
    answer: AnswerView | None = None


class CurrentQuestionResponse(BaseModel):
    status: InterviewStatus
    question: QuestionResponse | None
    all_questions_answered: bool


class AnswerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    text: AnswerText | None = None
    skip: bool = False

    @model_validator(mode="after")
    def _text_or_skip(self) -> "AnswerCreate":
        if self.skip:
            if self.text:
                raise ValueError("Send either an answer or skip=true, not both")
        elif not self.text:
            raise ValueError("Write an answer, or send skip=true to skip this question")
        return self


class EvaluationResponse(BaseModel):
    id: uuid.UUID
    answer_id: uuid.UUID
    question_id: uuid.UUID
    status: EvaluationStatus
    reason: str | None
    provider: str | None
    model: str | None
    result: EvaluationResult | None
    created_at: datetime


class AnswerSubmitted(BaseModel):
    answer: AnswerView
    evaluation: EvaluationResponse
    follow_up_asked: bool
    followups_note: str | None
    next_question: QuestionResponse | None
    all_questions_answered: bool
    progress: Progress


class ReportResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    created_at: datetime
    overall_score: int | None
    report: InterviewReportData


class SessionSummary(BaseModel):
    id: uuid.UUID
    status: InterviewStatus
    interview_types: list[str]
    difficulty: SessionDifficulty
    job_title: str | None
    mode: str | None
    created_at: datetime
    completed_at: datetime | None
