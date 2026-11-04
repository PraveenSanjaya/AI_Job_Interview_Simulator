"""Deterministic scoring and report assembly.

All numbers in a report are computed here from the stored evaluations by fixed, configurable
rules. The evaluator's per-dimension judgements are inputs; nothing here calls an AI. Anything
that could not be evaluated is reported as such and excluded, never guessed.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from app.interview.bank import QUESTION_BANK, normalise
from app.interview.config import DIMENSIONS, GROUPS, DimensionWeights, InterviewScoringConfig
from app.interview.schemas import (
    AIFeedback,
    EvaluationResult,
    GroupScore,
    InterviewReportData,
    PracticeQuestion,
    QuestionOutcome,
    ReportCounts,
    StudyTopic,
)
from app.models.enums import EvaluationStatus

STAR_ELEMENTS = ("situation", "task", "action", "result", "reflection")
MAX_LIST = 5


@dataclass
class Record:
    """One asked question with whatever happened to it."""

    question_id: str
    main_index: int
    followup_index: int
    category: str
    text: str
    tags: list[str]
    expected_points: list[str]
    answered: bool = False
    skipped: bool = False
    eval_status: EvaluationStatus | None = None
    evaluation: EvaluationResult | None = None
    score: float | None = field(default=None, init=False)


def question_score(result: EvaluationResult, weights: DimensionWeights) -> float | None:
    """Weighted mean (0-10) of the dimensions the evaluator could judge; ``None`` if none."""
    table = weights.model_dump()
    total = 0.0
    weight_sum = 0.0
    for name, dimension in result.dimensions.items():
        weight = table.get(name, 0.0)
        if dimension.score is not None and weight > 0:
            total += weight * dimension.score
            weight_sum += weight
    return total / weight_sum if weight_sum else None


def record_score(record: Record, config: InterviewScoringConfig) -> float | None:
    if record.skipped:
        return 0.0 if (config.skipped_counts_as_zero and record.followup_index == 0) else None
    if record.eval_status == EvaluationStatus.EVALUATED and record.evaluation is not None:
        return question_score(record.evaluation, config.weights)
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _label(tag: str) -> str:
    return tag.replace("_", " ")


def build_report(
    *,
    session_id: str,
    interview_types: list[str],
    difficulty: str,
    mode: str | None,
    job_title: str | None,
    planned: int,
    records: list[Record],
    config: InterviewScoringConfig,
    ai_feedback: AIFeedback | None,
    ai_feedback_status: str,
) -> InterviewReportData:
    for record in records:
        record.score = record_score(record, config)

    threads: dict[int, list[Record]] = defaultdict(list)
    for record in sorted(records, key=lambda r: (r.main_index, r.followup_index)):
        threads[record.main_index].append(record)

    thread_scores: dict[int, float] = {}
    outcomes: dict[int, QuestionOutcome] = {}
    for index, members in threads.items():
        weighted = [
            (config.followup_weight if m.followup_index else 1.0, m.score)
            for m in members
            if m.score is not None
        ]
        weight_sum = sum(w for w, _ in weighted)
        score = (
            sum(w * s for w, s in weighted if s is not None) / weight_sum if weight_sum else None
        )
        main = members[0]
        if score is not None:
            thread_scores[index] = score
        if main.skipped:
            status = "skipped"
        elif score is not None:
            status = "evaluated"
        elif main.answered:
            status = "not_evaluated"
        else:
            status = "not_asked"
        summary = main.evaluation.summary if main.evaluation else None
        outcomes[index] = QuestionOutcome(
            question_id=main.question_id,
            main_index=index,
            category=main.category,
            text=main.text,
            status=status,
            score=_round(score),
            summary=summary,
            tags=main.tags,
            followups_answered=sum(1 for m in members[1:] if m.answered and not m.skipped),
        )

    overall = _mean(list(thread_scores.values()))
    overall_score = None if overall is None else round(overall * 10)

    # Per-dimension means over evaluated answers (follow-ups count with their weight).
    per_dim: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for record in records:
        if record.eval_status == EvaluationStatus.EVALUATED and record.evaluation:
            weight = config.followup_weight if record.followup_index else 1.0
            for name, dim in record.evaluation.dimensions.items():
                if dim.score is not None and weight > 0:
                    per_dim[name].append((weight, dim.score))
    dimension_scores: dict[str, float | None] = {}
    for name in DIMENSIONS:
        pairs = per_dim.get(name, [])
        total = sum(w for w, _ in pairs)
        dimension_scores[name] = _round(sum(w * s for w, s in pairs) / total) if total else None

    table = config.weights.model_dump()
    group_scores: dict[str, GroupScore] = {}
    notes = {
        "knowledge": "Technical correctness, relevance and completeness of the content.",
        "approach": "How the problem was approached and applied in practice.",
        "communication": (
            "Clarity and use of examples. This is a subjective judgement of the written "
            "answer only; it infers nothing about confidence or personality."
        ),
    }
    for group, names in GROUPS.items():
        usable = [
            (table[n], dimension_scores[n])
            for n in names
            if dimension_scores[n] is not None and table[n] > 0
        ]
        weight_sum = sum(w for w, _ in usable)
        value = sum(w * s for w, s in usable if s is not None) / weight_sum if weight_sum else None
        group_scores[group] = GroupScore(
            score=_round(value), subjective=group == "communication", note=notes[group]
        )

    by_category: dict[str, list[float]] = defaultdict(list)
    for index, score in thread_scores.items():
        by_category[outcomes[index].category].append(score)
    category_scores = {c: _round(_mean(v)) for c, v in sorted(by_category.items())}

    scored = [o for o in outcomes.values() if o.score is not None]
    strong = sorted(
        (o for o in scored if (o.score or 0) >= config.strong_threshold),
        key=lambda o: -(o.score or 0),
    )
    weak = sorted(
        (o for o in scored if (o.score or 0) < config.weak_threshold), key=lambda o: o.score or 0
    )
    not_evaluated = [o for o in outcomes.values() if o.status == "not_evaluated"]

    gaps: list[str] = []
    for record in records:
        if (
            record.evaluation
            and record.score is not None
            and record.score < config.strong_threshold
        ):
            gaps.extend(record.evaluation.missing_or_incorrect_points)
    for record in records:
        if record.skipped and record.followup_index == 0:
            gaps.extend(f"Not addressed (question skipped): {p}" for p in record.expected_points)
    knowledge_gaps = list(dict.fromkeys(gaps))[:10]

    study: list[StudyTopic] = []
    weak_tags: list[str] = []
    for outcome in weak + [o for o in outcomes.values() if o.status == "skipped"]:
        reason = (
            "Skipped during the interview."
            if outcome.status == "skipped"
            else f"The answer scored {outcome.score}/10."
        )
        for tag in outcome.tags or [outcome.category]:
            if tag not in weak_tags:
                weak_tags.append(tag)
                study.append(StudyTopic(topic=_label(tag).capitalize(), reason=reason))
    study = study[:10]

    asked_texts = {normalise(r.text) for r in records}
    practice: list[PracticeQuestion] = []
    for tag in weak_tags[:MAX_LIST]:
        for question in QUESTION_BANK:
            if tag in question.tags and normalise(question.text) not in asked_texts:
                practice.append(PracticeQuestion(text=question.text, topic=_label(tag)))
                asked_texts.add(normalise(question.text))
                break

    star_summary: dict[str, str] | None = None
    star_records = [r.evaluation.star for r in records if r.evaluation and r.evaluation.star]
    if star_records:
        star_summary = {}
        for element in STAR_ELEMENTS:
            flags = [getattr(s, element).present for s in star_records]
            known = [f for f in flags if f is not None]
            if known:
                star_summary[element] = (
                    f"{sum(known)} of {len(known)} behavioral answers covered it"
                )

    mains = [r for r in records if r.followup_index == 0]
    followups = [r for r in records if r.followup_index > 0]
    evaluated = [r for r in records if r.eval_status == EvaluationStatus.EVALUATED]
    counts = ReportCounts(
        main_questions_planned=planned,
        main_questions_asked=len(mains),
        answered=sum(1 for r in records if r.answered and not r.skipped),
        skipped=sum(1 for r in records if r.skipped),
        followups_asked=len(followups),
        followups_answered=sum(1 for r in followups if r.answered and not r.skipped),
        evaluated_answers=len(evaluated),
        not_evaluated_answers=sum(
            1
            for r in records
            if r.answered and not r.skipped and r.eval_status != EvaluationStatus.EVALUATED
        ),
    )

    calc = [
        "Each answer's score is the weighted mean (0-10) of the dimensions the evaluator could "
        "judge; dimensions it could not judge are left out and the weights rescaled.",
        f"A follow-up answer counts {config.followup_weight:g}x as much as its main question.",
        "A skipped main question scores 0."
        if config.skipped_counts_as_zero
        else "Skipped questions are excluded from the score.",
        "Questions never asked and answers that could not be evaluated are excluded, not scored 0.",
        "Overall score = mean of the question scores x 10.",
    ]
    if overall_score is None:
        explanation = (
            "No score was calculated because none of the answers could be evaluated. "
            "Your answers are saved; evaluation needs an available AI provider."
        )
    else:
        explanation = (
            f"{overall_score}/100 = mean of {len(thread_scores)} question score(s) "
            f"({', '.join(f'{s:.1f}' for _, s in sorted(thread_scores.items()))}) x 10."
        )

    return InterviewReportData(
        session_id=session_id,
        interview_types=interview_types,
        difficulty=difficulty,
        mode=mode,
        job_title=job_title,
        counts=counts,
        overall_score=overall_score,
        score_status="scored" if overall_score is not None else "not_evaluated",
        score_explanation=explanation,
        dimension_scores=dimension_scores,
        group_scores=group_scores,
        category_scores=category_scores,
        star_summary=star_summary,
        strong_answers=strong[:MAX_LIST],
        weak_answers=weak[:MAX_LIST],
        not_evaluated=not_evaluated,
        knowledge_gaps=knowledge_gaps,
        study_topics=study,
        practice_questions=practice[:MAX_LIST],
        ai_feedback=ai_feedback,
        ai_feedback_status=ai_feedback_status,
        calculation_notes=calc,
        scoring_config=config,
    )
