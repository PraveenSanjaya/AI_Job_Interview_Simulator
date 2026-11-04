"""Validated structures for AI output (questions, follow-ups, evaluations, feedback) and for
the stored interview report.

Model output is parsed leniently where that is safe (trimming, clamping scores to 0-10,
dropping unknown keys, capping list lengths) and strictly where it matters (structure, and
at least one real score in an evaluation).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.interview.config import DIMENSIONS, InterviewScoringConfig

FollowUpKind = Literal[
    "clarification", "rationale", "trade_offs", "example", "challenge", "alternatives"
]
FOLLOWUP_KINDS = {
    "clarification",
    "rationale",
    "trade_offs",
    "example",
    "challenge",
    "alternatives",
}


def _text(limit: int) -> Any:
    def clean(value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("expected text")
        return " ".join(str(value).split())[:limit] or None

    return BeforeValidator(clean)


def _text_list(limit: int, max_items: int) -> Any:
    one = _text(limit).func

    def clean(value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expected a list")
        seen: set[str] = set()
        out: list[str] = []
        for raw in value:
            item = one(raw)
            if item and item.casefold() not in seen:
                seen.add(item.casefold())
                out.append(item)
            if len(out) >= max_items:
                break
        return out

    return BeforeValidator(clean)


def _score(value: object) -> int | None:
    """0-10 integer, ``None`` for anything that is not a real number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, int | float) or value != value:  # NaN
        return None
    return max(0, min(10, round(value)))


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


Short = Annotated[str | None, _text(300)]
Long = Annotated[str | None, _text(1200)]
Points = Annotated[list[str], _text_list(300, 8)]


# ------------------------------------------------------------------ questions


class GeneratedQuestion(_Lenient):
    category: Annotated[str | None, _text(20)] = None
    text: Annotated[str | None, _text(600)] = None
    skill_tags: Annotated[list[str], _text_list(40, 6)] = Field(default_factory=list)
    expected_points: Annotated[list[str], _text_list(200, 6)] = Field(default_factory=list)
    # For project questions: the exact project name from the supplied evidence.
    project: Annotated[str | None, _text(200)] = None


class QuestionSetOutput(_Lenient):
    questions: Annotated[list[GeneratedQuestion], BeforeValidator(lambda v: _list(v, 40))] = Field(
        default_factory=list
    )


def _list(value: object, limit: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return value[:limit]


class FollowUpItem(_Lenient):
    kind: Annotated[str | None, _text(20)] = None
    text: Annotated[str | None, _text(500)] = None


class FollowUpOutput(_Lenient):
    follow_up: FollowUpItem | None = None


# ---------------------------------------------------------------- evaluation


class DimensionResult(_Lenient):
    score: Annotated[int | None, BeforeValidator(_score)] = None
    rationale: Short = None


class StarElement(_Lenient):
    present: bool | None = None
    note: Short = None


class StarAssessment(_Lenient):
    situation: StarElement = Field(default_factory=StarElement)
    task: StarElement = Field(default_factory=StarElement)
    action: StarElement = Field(default_factory=StarElement)
    result: StarElement = Field(default_factory=StarElement)
    reflection: StarElement = Field(default_factory=StarElement)


def _dimensions(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return {k: v for k, v in value.items() if k in DIMENSIONS}


class EvaluationResult(_Lenient):
    """Stored evaluation of one answer. Scores are the evaluator's judgement (0-10);
    ``None`` means "could not be judged", never zero."""

    dimensions: Annotated[dict[str, DimensionResult], BeforeValidator(_dimensions)] = Field(
        default_factory=dict
    )
    star: StarAssessment | None = None
    correct_points: Points = Field(default_factory=list)
    missing_or_incorrect_points: Points = Field(default_factory=list)
    strengths: Points = Field(default_factory=list)
    improvements: Points = Field(default_factory=list)
    summary: Long = None
    not_evaluable: Annotated[list[str], _text_list(100, 8)] = Field(default_factory=list)
    # Set by code (not the model) when the answer contained instruction-like text.
    suspicious_instructions: bool = False

    def has_any_score(self) -> bool:
        return any(d.score is not None for d in self.dimensions.values())


# ------------------------------------------------------------------ feedback


class StudyTopic(_Lenient):
    topic: Short = None
    reason: Long = None
    source: Literal["deterministic", "ai"] = "deterministic"


class FeedbackOutput(_Lenient):
    summary: Long = None
    study_topics: Annotated[list[StudyTopic], BeforeValidator(lambda v: _list(v, 8))] = Field(
        default_factory=list
    )
    practice_questions: Annotated[list[str], _text_list(400, 6)] = Field(default_factory=list)


class AIFeedback(_Lenient):
    summary: Long = None
    study_topics: list[StudyTopic] = Field(default_factory=list)
    practice_questions: list[str] = Field(default_factory=list)
    notice: str = (
        "AI-generated feedback. It explains the results above and may be incomplete or wrong; "
        "the scores are authoritative."
    )


# -------------------------------------------------------------------- report


class QuestionOutcome(BaseModel):
    question_id: str
    main_index: int
    category: str
    text: str
    status: Literal["evaluated", "skipped", "not_evaluated", "not_asked"]
    score: float | None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    followups_answered: int = 0


class PracticeQuestion(BaseModel):
    text: str
    topic: str | None = None
    source: Literal["question_bank", "ai"] = "question_bank"


class GroupScore(BaseModel):
    score: float | None
    subjective: bool = False
    note: str


class ReportCounts(BaseModel):
    main_questions_planned: int
    main_questions_asked: int
    answered: int
    skipped: int
    followups_asked: int
    followups_answered: int
    evaluated_answers: int
    not_evaluated_answers: int


class InterviewReportData(BaseModel):
    session_id: str
    interview_types: list[str]
    difficulty: str
    mode: str | None
    job_title: str | None
    counts: ReportCounts
    overall_score: int | None
    score_status: Literal["scored", "not_evaluated"]
    score_explanation: str
    dimension_scores: dict[str, float | None]
    group_scores: dict[str, GroupScore]
    category_scores: dict[str, float | None]
    star_summary: dict[str, str] | None = None
    strong_answers: list[QuestionOutcome]
    weak_answers: list[QuestionOutcome]
    not_evaluated: list[QuestionOutcome]
    knowledge_gaps: list[str]
    study_topics: list[StudyTopic]
    practice_questions: list[PracticeQuestion]
    ai_feedback: AIFeedback | None = None
    ai_feedback_status: str
    calculation_notes: list[str]
    scoring_config: InterviewScoringConfig
    disclaimer: str = (
        "A mock-interview score reflects how the answers given here were judged under the "
        "stated rules. It is practice feedback, not a predictor of any real hiring outcome, "
        "and it says nothing about personality, confidence or honesty."
    )
