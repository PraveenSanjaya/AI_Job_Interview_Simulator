"""State machine, scoring rules, question bank and evaluation schema (no HTTP, no AI)."""

import random

import pytest
from pydantic import ValidationError

from app.interview.bank import (
    QUESTION_BANK,
    job_specific_prompts,
    normalise,
    pick_for_category,
    tags_for_skills,
)
from app.interview.config import (
    DIMENSIONS,
    TRANSITIONS,
    InterviewScoringConfig,
    resolve_scoring,
    sources_for,
)
from app.interview.schemas import EvaluationResult
from app.interview.scoring import Record, build_report, question_score
from app.models.enums import EvaluationStatus, InterviewStatus, InterviewType


def evaluation(**scores: int | None) -> EvaluationResult:
    return EvaluationResult.model_validate(
        {
            "dimensions": {k: {"score": v, "rationale": "r"} for k, v in scores.items()},
            "summary": "ok",
            "missing_or_incorrect_points": ["Mentions nothing about indexes"],
        }
    )


def record(
    index: int,
    follow: int = 0,
    *,
    scores: dict[str, int | None] | None = None,
    skipped: bool = False,
    status: EvaluationStatus | None = None,
    category: str = "technical",
    tags: list[str] | None = None,
) -> Record:
    evaluated = scores is not None
    return Record(
        question_id=f"q{index}-{follow}",
        main_index=index,
        followup_index=follow,
        category=category,
        text=f"Question {index}.{follow}?",
        tags=tags or ["sql"],
        expected_points=["indexes", "joins"],
        answered=True,
        skipped=skipped,
        eval_status=status or (EvaluationStatus.EVALUATED if evaluated else None),
        evaluation=evaluation(**scores) if scores is not None else None,
    )


def report(records: list[Record], config: InterviewScoringConfig | None = None, planned: int = 3):  # type: ignore[no-untyped-def]
    return build_report(
        session_id="s1",
        interview_types=["technical"],
        difficulty="intermediate",
        mode="ai",
        job_title=None,
        planned=planned,
        records=records,
        config=config or InterviewScoringConfig(),
        ai_feedback=None,
        ai_feedback_status="not_requested",
    )


# ------------------------------------------------------------- state machine


def test_every_state_is_covered_and_terminal_states_are_final() -> None:
    assert set(TRANSITIONS) == set(InterviewStatus)
    for final in (InterviewStatus.COMPLETED, InterviewStatus.CANCELLED, InterviewStatus.EXPIRED):
        assert TRANSITIONS[final] == frozenset()


def test_allowed_transitions() -> None:
    assert sources_for(InterviewStatus.IN_PROGRESS) == {
        InterviewStatus.CREATED,
        InterviewStatus.INTERRUPTED,
    }
    assert InterviewStatus.CREATED not in sources_for(InterviewStatus.COMPLETED)  # no skipping
    assert InterviewStatus.COMPLETED not in sources_for(InterviewStatus.CANCELLED)
    assert InterviewStatus.IN_PROGRESS not in sources_for(InterviewStatus.CREATED)


# ------------------------------------------------------------------ bank


def test_bank_covers_every_category_and_difficulty() -> None:
    for category in ("hr", "behavioral", "technical", "programming", "project", "system_design"):
        for level in ("beginner", "intermediate", "advanced"):
            assert [q for q in QUESTION_BANK if q.category == category and q.difficulty == level]
    assert {t.value for t in InterviewType} - {"job_specific"} == {
        q.category for q in QUESTION_BANK
    }


def test_bank_entries_are_unique_and_never_state_facts_about_the_candidate() -> None:
    texts = [normalise(q.text) for q in QUESTION_BANK]
    assert len(texts) == len(set(texts))
    assert len({q.id for q in QUESTION_BANK}) == len(QUESTION_BANK)
    for q in QUESTION_BANK:
        assert q.key_points and q.text.endswith(("?", "."))
        if q.category == "project":
            assert q.text.startswith("Choose a project")  # generic: no assumed project


def test_pick_prefers_requested_tags_then_difficulty_and_excludes_asked() -> None:
    rng = random.Random(1)
    picked = pick_for_category(
        "technical", "intermediate", 3, preferred_tags=["sql", "git"], exclude=set(), rng=rng
    )
    assert [q.tags[0] for q in picked][:2] == ["sql", "git"]
    assert picked[0].difficulty == "intermediate"
    again = pick_for_category(
        "technical",
        "intermediate",
        3,
        preferred_tags=["sql"],
        exclude={normalise(picked[0].text)},
        rng=random.Random(1),
    )
    assert normalise(picked[0].text) not in {normalise(q.text) for q in again}


def test_pick_is_reproducible_for_a_seed_and_never_exceeds_the_pool() -> None:
    def run(seed: int) -> list[str]:
        qs = pick_for_category(
            "hr", "beginner", 50, preferred_tags=[], exclude=set(), rng=random.Random(seed)
        )
        return [q.id for q in qs]

    assert run(7) == run(7)
    assert len(run(7)) == len({q.id for q in QUESTION_BANK if q.category == "hr"})


def test_skills_map_to_tags() -> None:
    assert tags_for_skills(["PostgreSQL", "FastAPI", "Docker", "Unknown Thing", "MySQL"]) == [
        "sql",
        "python",
        "containers",
    ]


def test_job_specific_prompts_quote_the_job_duties() -> None:
    prompts = job_specific_prompts(["Maintain the billing API"], "advanced", 3)
    assert len(prompts) == 1
    assert "Maintain the billing API" in prompts[0][0]


# ------------------------------------------------------------------ config


def test_scoring_config_defaults_and_overrides_merge_per_dimension() -> None:
    config = resolve_scoring({"weights": {"clarity": 0.2}}, {"weights": {"relevance": 0.0}})
    assert config.weights.clarity == 0.2 and config.weights.relevance == 0.0
    assert config.weights.technical_correctness == 0.30
    assert config.followup_weight == 0.5


@pytest.mark.parametrize(
    "override",
    [
        {"weights": {"nonsense": 1}},
        {"weights": {"clarity": -1}},
        {"followup_weight": 2},
        {"strong_threshold": 3, "weak_threshold": 6},
        {"unknown": 1},
        {"weights": dict.fromkeys(DIMENSIONS, 0)},
    ],
)
def test_invalid_scoring_overrides_are_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        resolve_scoring(None, override)


# ------------------------------------------------------------------ scoring


def test_question_score_is_a_weighted_mean_over_judged_dimensions() -> None:
    config = InterviewScoringConfig()
    result = evaluation(technical_correctness=10, clarity=0, relevance=None)
    # weights 0.30 and 0.10: (3.0 + 0.0) / 0.40
    assert question_score(result, config.weights) == pytest.approx(7.5)
    assert question_score(evaluation(relevance=None), config.weights) is None


def test_clamping_and_garbage_scores() -> None:
    result = EvaluationResult.model_validate(
        {
            "dimensions": {
                "clarity": {"score": 99},
                "relevance": {"score": "7"},
                "completeness": {"score": True},
                "problem_solving": {"score": "n/a"},
                "made_up": {"score": 5},
            }
        }
    )
    assert result.dimensions["clarity"].score == 10
    assert result.dimensions["relevance"].score == 7
    assert result.dimensions["completeness"].score is None
    assert result.dimensions["problem_solving"].score is None
    assert "made_up" not in result.dimensions
    assert result.has_any_score()
    assert not EvaluationResult().has_any_score()


def test_overall_score_is_mean_of_question_scores_times_ten() -> None:
    records = [
        record(0, scores={"technical_correctness": 8}),
        record(1, scores={"technical_correctness": 4}),
    ]
    result = report(records)
    assert result.overall_score == 60
    assert result.score_status == "scored"
    assert result.score_explanation.startswith("60/100 = mean of 2 question score(s)")
    assert result.counts.evaluated_answers == 2


def test_followups_count_less_than_their_main_question() -> None:
    records = [
        record(0, scores={"technical_correctness": 10}),
        record(0, 1, scores={"technical_correctness": 4}),
    ]
    assert report(records).overall_score == 80  # (10 + 0.5 * 4) / 1.5 = 8.0
    full = InterviewScoringConfig(followup_weight=1.0)
    assert report(records, full).overall_score == 70


def test_skipped_questions_score_zero_unless_configured_otherwise() -> None:
    records = [record(0, scores={"technical_correctness": 10}), record(1, skipped=True)]
    assert report(records).overall_score == 50
    lenient = InterviewScoringConfig(skipped_counts_as_zero=False)
    assert report(records, lenient).overall_score == 100
    assert report(records).counts.skipped == 1


def test_a_skipped_followup_is_not_penalised() -> None:
    records = [
        record(0, scores={"technical_correctness": 10}),
        record(0, 1, skipped=True),
    ]
    assert report(records).overall_score == 100


def test_unevaluated_answers_are_excluded_not_zeroed() -> None:
    records = [
        record(0, scores={"technical_correctness": 6}),
        record(1, status=EvaluationStatus.UNAVAILABLE),
    ]
    result = report(records)
    assert result.overall_score == 60
    assert [o.main_index for o in result.not_evaluated] == [1]
    assert result.counts.not_evaluated_answers == 1


def test_nothing_evaluated_means_no_score_at_all() -> None:
    result = report([record(0, status=EvaluationStatus.UNAVAILABLE)])
    assert result.overall_score is None
    assert result.score_status == "not_evaluated"
    assert "evaluation needs an available AI provider" in result.score_explanation
    assert result.category_scores == {} and result.strong_answers == []


def test_score_boundaries() -> None:
    top = report([record(0, scores=dict.fromkeys(DIMENSIONS, 10))])
    bottom = report([record(0, scores=dict.fromkeys(DIMENSIONS, 0))])
    assert top.overall_score == 100 and bottom.overall_score == 0


def test_strong_weak_gaps_topics_and_practice() -> None:
    records = [
        record(0, scores=dict.fromkeys(DIMENSIONS, 9), tags=["python"]),
        record(1, scores=dict.fromkeys(DIMENSIONS, 2), tags=["git"]),
        record(2, skipped=True, tags=["linux"]),
    ]
    result = report(records)
    assert [o.main_index for o in result.strong_answers] == [0]
    weak_indexes = {o.main_index for o in result.weak_answers}
    assert weak_indexes == {1, 2}
    assert "Mentions nothing about indexes" in result.knowledge_gaps
    assert "Not addressed (question skipped): indexes" in result.knowledge_gaps
    topics = {t.topic: t.reason for t in result.study_topics}
    assert topics["Git"] == "The answer scored 2.0/10."
    assert topics["Linux"] == "Skipped during the interview."
    assert "Python" not in topics
    assert {p.topic for p in result.practice_questions} == {"git", "linux"}
    assert all(p.source == "question_bank" for p in result.practice_questions)
    assert not {normalise(p.text) for p in result.practice_questions} & {
        normalise(r.text) for r in records
    }


def test_groups_separate_objective_from_subjective_communication() -> None:
    result = report(
        [record(0, scores={"technical_correctness": 9, "problem_solving": 6, "clarity": 3})]
    )
    assert result.group_scores["knowledge"].score == 9.0
    assert result.group_scores["approach"].score == 6.0
    assert result.group_scores["communication"].score == 3.0
    assert result.group_scores["communication"].subjective is True
    assert result.group_scores["knowledge"].subjective is False
    assert "infers nothing about confidence" in result.group_scores["communication"].note
    assert result.dimension_scores["relevance"] is None  # not judged -> not zero


def test_category_scores_and_verbosity_is_not_a_factor() -> None:
    records = [
        record(0, category="technical", scores={"technical_correctness": 8}),
        record(1, category="hr", scores={"technical_correctness": 4}),
    ]
    result = report(records)
    assert result.category_scores == {"hr": 4.0, "technical": 8.0}
    # Answer length is not an input anywhere in the scoring functions.
    assert "length" not in " ".join(result.calculation_notes).casefold()


def test_star_summary_counts_covered_elements() -> None:
    star = {
        "situation": {"present": True},
        "task": {"present": True},
        "action": {"present": True},
        "result": {"present": False},
        "reflection": {"present": None},
    }
    rec = record(0, category="behavioral", scores={"relevance": 7})
    assert rec.evaluation is not None
    rec.evaluation = EvaluationResult.model_validate({**rec.evaluation.model_dump(), "star": star})
    summary = report([rec]).star_summary
    assert summary is not None
    assert summary["situation"] == "1 of 1 behavioral answers covered it"
    assert summary["result"] == "0 of 1 behavioral answers covered it"
    assert "reflection" not in summary  # could not be judged


def test_disclaimer_denies_predictive_value() -> None:
    text = report([record(0, scores={"relevance": 5})]).disclaimer
    assert "not a predictor of any real hiring outcome" in text
    assert "personality, confidence or honesty" in text
