"""Mock interview API: sessions, state machine, question bank mode, ownership."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.interview.bank import QUESTION_BANK
from app.models import InterviewAnswer, InterviewSession
from tests.helpers import bearer, register_and_login
from tests.samples_jobs import BACKEND_JOB

pytestmark = pytest.mark.anyio

IV = "/api/v1/interviews"
JOBS = "/api/v1/jobs"
BANK_BY_TEXT = {q.text: q for q in QUESTION_BANK}


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def create(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> httpx.Response:
    body: dict[str, Any] = {
        "interview_types": ["technical"],
        "difficulty": "beginner",
        "question_count": 3,
    }
    body.update(overrides)
    return await client.post(IV, headers=headers, json=body)


async def started(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    created = await create(client, headers, **overrides)
    assert created.status_code == 201, created.text
    response = await client.post(f"{IV}/{created.json()['id']}/start", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def current(
    client: httpx.AsyncClient, headers: dict[str, str], session_id: str
) -> dict[str, Any]:
    response = await client.get(f"{IV}/{session_id}/current-question", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def answer(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    session_id: str,
    question_id: str,
    text: str | None = "My answer explains the idea with a short example.",
    **extra: Any,
) -> httpx.Response:
    body: dict[str, Any] = {"question_id": question_id}
    if text is not None:
        body["text"] = text
    return await client.post(f"{IV}/{session_id}/answers", headers=headers, json=body | extra)


async def answer_all(
    client: httpx.AsyncClient, headers: dict[str, str], session_id: str, limit: int = 40
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for _ in range(limit):
        question = (await current(client, headers, session_id))["question"]
        if question is None:
            break
        response = await answer(client, headers, session_id, question["id"])
        assert response.status_code == 201, response.text
        results.append(response.json())
    return results


# ------------------------------------------------------------- create & read


async def test_create_returns_a_configured_unstarted_session(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await create(
        client,
        headers,
        interview_types=["technical", "hr"],
        difficulty="intermediate",
        question_count=10,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "created"
    assert body["interview_types"] == ["technical", "hr"]
    assert (body["difficulty"], body["question_count"], body["max_followups"]) == (
        "intermediate",
        10,
        2,
    )
    assert body["mode"] is None and body["started_at"] is None and body["job_id"] is None
    assert body["scoring_config"]["weights"]["technical_correctness"] == 0.30
    assert body["progress"]["main_questions_asked"] == 0
    listing = (await client.get(IV, headers=headers)).json()
    assert [i["id"] for i in listing] == [body["id"]]
    assert (await client.get(f"{IV}/{body['id']}", headers=headers)).json() == body
    # No questions exist before the interview is started.
    assert (await client.get(f"{IV}/{body['id']}/questions", headers=headers)).json() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"interview_types": []},
        {"interview_types": ["technical", "technical"]},
        {"interview_types": ["astrology"]},
        {"difficulty": "expert"},
        {"question_count": 0},
        {"question_count": 101},
        {"question_count": 31},
        {"interview_types": ["technical", "hr", "project"], "question_count": 2},
        {"interview_types": ["job_specific"]},
        {"max_followups": 4},
        {"max_followups": -1},
        {"scoring": {"weights": {"nonsense": 1}}},
        {"scoring": {"followup_weight": 5}},
        {"unexpected": True},
    ],
)
async def test_invalid_configuration_is_rejected(
    client: httpx.AsyncClient, overrides: dict[str, Any]
) -> None:
    headers = await headers_for(client)
    response = await create(client, headers, **overrides)
    assert response.status_code in (404, 422), overrides
    assert (await client.get(IV, headers=headers)).json() == []


async def test_unknown_job_is_not_found_and_other_users_jobs_are_hidden(
    client: httpx.AsyncClient,
) -> None:
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    job = await client.post(
        JOBS, headers=ada, json={"title": "Backend Engineer", "description": BACKEND_JOB}
    )
    assert (await create(client, eve, job_id=job.json()["id"])).status_code == 404
    assert (await create(client, ada, job_id=job.json()["id"])).status_code == 201


async def test_server_scoring_rules_and_request_overrides(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    settings.interview_scoring = {"followup_weight": 0.25, "weights": {"clarity": 0.2}}
    headers = await headers_for(client)
    body = (
        await create(
            client, headers, scoring={"followup_weight": 0.75, "skipped_counts_as_zero": False}
        )
    ).json()
    config = body["scoring_config"]
    assert config["followup_weight"] == 0.75
    assert config["weights"]["clarity"] == 0.2
    assert config["skipped_counts_as_zero"] is False


# ---------------------------------------------------------- state machine


async def test_the_state_machine_blocks_illegal_moves(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await create(client, headers)).json()["id"]
    question_id = "00000000-0000-0000-0000-000000000000"

    assert (await answer(client, headers, sid, question_id)).status_code == 409  # not started
    assert (await client.post(f"{IV}/{sid}/complete", headers=headers)).status_code == 409
    assert (await client.get(f"{IV}/{sid}/report", headers=headers)).json()["error"]["code"] == (
        "report_not_ready"
    )
    assert (await current(client, headers, sid))["question"] is None

    assert (await client.post(f"{IV}/{sid}/start", headers=headers)).status_code == 200
    again = await client.post(f"{IV}/{sid}/start", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_interview_state"

    done = await client.post(f"{IV}/{sid}/complete", headers=headers)
    assert done.status_code == 200
    for method, path in [("POST", "start"), ("POST", "complete"), ("POST", "cancel")]:
        response = await client.request(method, f"{IV}/{sid}/{path}", headers=headers)
        assert response.status_code == 409, path
    late = await answer(client, headers, sid, question_id)
    assert late.status_code == 409 and late.json()["error"]["code"] == "invalid_interview_state"
    assert (await client.get(f"{IV}/{sid}", headers=headers)).json()["status"] == "completed"


async def test_cancelled_sessions_are_final(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await create(client, headers)).json()["id"]
    cancelled = await client.post(f"{IV}/{sid}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    for path in ("start", "complete", "cancel"):
        assert (await client.post(f"{IV}/{sid}/{path}", headers=headers)).status_code == 409
    running = (await started(client, headers))["id"]
    assert (await client.post(f"{IV}/{running}/cancel", headers=headers)).status_code == 200
    question_id = "00000000-0000-0000-0000-000000000000"
    assert (await answer(client, headers, running, question_id)).status_code == 409


async def set_session(session: AsyncSession, session_id: str, **values: Any) -> None:
    await session.execute(
        update(InterviewSession)
        .where(InterviewSession.id == uuid.UUID(session_id))
        .values(**values)
    )
    await session.commit()


async def test_idle_interviews_are_interrupted_and_can_be_resumed(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers))["id"]
    await set_session(
        session,
        sid,
        last_activity_at=datetime.now(UTC) - timedelta(minutes=settings.interview_idle_minutes + 5),
    )
    body = (await client.get(f"{IV}/{sid}", headers=headers)).json()
    assert body["status"] == "interrupted"
    question = (await current(client, headers, sid))["question"]
    assert question is not None  # still visible so the candidate can see where they were
    blocked = await answer(client, headers, sid, question["id"])
    assert blocked.status_code == 409

    resumed = await client.post(f"{IV}/{sid}/start", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["status"] == "in_progress"
    assert (await answer(client, headers, sid, question["id"])).status_code == 201
    assert resumed.json()["progress"]["main_questions_asked"] == 1  # nothing was regenerated


async def test_interrupted_interviews_can_be_completed_or_cancelled(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    old = datetime.now(UTC) - timedelta(days=2)
    for action in ("complete", "cancel"):
        sid = (await started(client, headers))["id"]
        await set_session(session, sid, last_activity_at=old)
        assert (await client.post(f"{IV}/{sid}/{action}", headers=headers)).status_code == 200


async def test_unstarted_interviews_expire(
    client: httpx.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    headers = await headers_for(client)
    sid = (await create(client, headers)).json()["id"]
    await set_session(
        session,
        sid,
        created_at=datetime.now(UTC) - timedelta(hours=settings.interview_created_expiry_hours + 1),
    )
    assert (await client.get(f"{IV}/{sid}", headers=headers)).json()["status"] == "expired"
    assert (await client.post(f"{IV}/{sid}/start", headers=headers)).status_code == 409
    assert (await client.get(IV, headers=headers)).json()[0]["status"] == "expired"


# ------------------------------------------------------ question bank (no AI)


async def test_without_an_ai_provider_the_question_bank_runs_the_interview(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    body = await started(client, headers, question_count=3)
    assert body["status"] == "in_progress" and body["started_at"]
    assert (body["mode"], body["ai_status"]) == ("question_bank", "provider_unavailable")
    assert body["adaptive_followups"] is False
    assert any(
        "Adaptive follow-ups and answer evaluation are unavailable" in n for n in body["notes"]
    )
    assert body["ai_provider"] is None
    assert body["progress"] == {
        "main_questions_total": 3,
        "main_questions_asked": 1,
        "answered": 0,
        "skipped": 0,
        "followups_asked": 0,
        "remaining_main_questions": 2,
    }

    first = (await current(client, headers, body["id"]))["question"]
    assert first["main_index"] == 0 and first["source"] == "question_bank"
    assert first["text"] in BANK_BY_TEXT
    assert "expected_points" not in first  # never revealed during the interview

    asked = (await client.get(f"{IV}/{body['id']}/questions", headers=headers)).json()
    assert [q["id"] for q in asked] == [first["id"]]  # later questions stay hidden

    submitted = await answer(client, headers, body["id"], first["id"])
    assert submitted.status_code == 201, submitted.text
    result = submitted.json()
    assert result["evaluation"]["status"] == "unavailable"
    assert result["evaluation"]["result"] is None
    assert result["evaluation"]["reason"] == "ai_not_used:provider_unavailable"
    assert result["follow_up_asked"] is False
    assert "unavailable" in result["followups_note"]
    assert result["next_question"]["main_index"] == 1
    assert result["progress"]["answered"] == 1
    assert result["progress"]["main_questions_asked"] == 2


async def test_full_bank_interview_and_unscored_report(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers, question_count=3))["id"]
    results = await answer_all(client, headers, sid)
    assert len(results) == 3
    assert results[-1]["next_question"] is None and results[-1]["all_questions_answered"] is True
    state = await current(client, headers, sid)
    assert state["question"] is None and state["all_questions_answered"] is True
    assert (await client.get(f"{IV}/{sid}", headers=headers)).json()["status"] == "in_progress"

    report = await client.post(f"{IV}/{sid}/complete", headers=headers)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["overall_score"] is None
    data = body["report"]
    assert data["score_status"] == "not_evaluated"
    assert "evaluation needs an available AI provider" in data["score_explanation"]
    assert data["counts"]["answered"] == 3 and data["counts"]["evaluated_answers"] == 0
    assert len(data["not_evaluated"]) == 3
    assert data["ai_feedback"] is None and data["ai_feedback_status"].startswith("unavailable")
    assert "not a predictor of any real hiring outcome" in data["disclaimer"]
    assert (await client.get(f"{IV}/{sid}/report", headers=headers)).json() == body

    evaluations = (await client.get(f"{IV}/{sid}/evaluations", headers=headers)).json()
    assert len(evaluations) == 3 and {e["status"] for e in evaluations} == {"unavailable"}


async def test_skipping_and_early_completion(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers, question_count=4))["id"]
    first = (await current(client, headers, sid))["question"]
    skipped = await answer(client, headers, sid, first["id"], None, skip=True)
    assert skipped.status_code == 201
    assert skipped.json()["answer"]["skipped"] is True and skipped.json()["answer"]["text"] is None
    assert skipped.json()["evaluation"]["status"] == "not_evaluated"
    assert skipped.json()["evaluation"]["reason"] == "skipped"

    report = (await client.post(f"{IV}/{sid}/complete", headers=headers)).json()["report"]
    assert report["counts"]["skipped"] == 1
    assert report["counts"]["main_questions_asked"] == 2  # the second was asked, never answered
    assert report["counts"]["main_questions_planned"] == 4
    statuses = {o["status"] for o in report["weak_answers"]}
    assert statuses == {"skipped"} or report["weak_answers"][0]["score"] == 0
    assert report["overall_score"] == 0  # a skipped question scores 0; unasked ones are excluded
    assert any("Skipped during the interview" in t["reason"] for t in report["study_topics"])


@pytest.mark.parametrize(
    "build",
    [
        lambda qid: {"text": "x"},
        lambda qid: {"question_id": "nope", "text": "x"},
        lambda qid: {},
        lambda qid: {"question_id": qid},
        lambda qid: {"question_id": qid, "skip": True, "text": "x"},
        lambda qid: {"question_id": qid, "text": "x" * 8001},
        lambda qid: {"question_id": qid, "text": "x", "evaluation": "perfect"},
    ],
)
async def test_invalid_answer_bodies_are_rejected(client: httpx.AsyncClient, build: Any) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers))["id"]
    first = (await current(client, headers, sid))["question"]
    response = await client.post(f"{IV}/{sid}/answers", headers=headers, json=build(first["id"]))
    assert response.status_code == 422
    assert (await current(client, headers, sid))["question"]["id"] == first["id"]


async def test_whitespace_only_answer_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers))["id"]
    first = (await current(client, headers, sid))["question"]
    assert (await answer(client, headers, sid, first["id"], "   \n ")).status_code == 422


# ----------------------------------------------------------- question quality


async def test_difficulty_is_respected_by_the_bank(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    for level in ("beginner", "advanced"):
        sid = (await started(client, headers, difficulty=level, question_count=5))["id"]
        results = await answer_all(client, headers, sid)
        asked = (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
        assert len(asked) == len(results) == 5
        assert {BANK_BY_TEXT[q["text"]].difficulty for q in asked} == {level}
        await client.post(f"{IV}/{sid}/cancel", headers=headers)


async def test_interview_types_share_the_questions_and_alternate(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (
        await started(
            client,
            headers,
            interview_types=["hr", "behavioral", "technical"],
            difficulty="intermediate",
            question_count=7,
        )
    )["id"]
    await answer_all(client, headers, sid)
    asked = (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
    categories = [q["category"] for q in asked]
    assert len(categories) == 7
    assert sorted(categories) == sorted(["hr"] * 3 + ["behavioral"] * 2 + ["technical"] * 2)
    assert categories[:3] == ["hr", "behavioral", "technical"]  # interleaved, not blocked


async def test_every_category_works_without_ai(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    types = ["hr", "behavioral", "technical", "programming", "project", "system_design"]
    sid = (await started(client, headers, interview_types=types, question_count=6))["id"]
    await answer_all(client, headers, sid)
    asked = (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
    assert {q["category"] for q in asked} == set(types)
    project = next(q for q in asked if q["category"] == "project")
    assert project["text"].startswith("Choose a project")  # generic: assumes no project


async def test_questions_are_not_repeated_across_interviews(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    seen: set[str] = set()
    for _ in range(3):
        sid = (await started(client, headers, interview_types=["technical"], question_count=6))[
            "id"
        ]
        await answer_all(client, headers, sid)
        texts = {
            q["text"] for q in (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
        }
        assert len(texts) == 6 and not texts & seen
        seen |= texts


JOB_WITH_DUTIES = """\
Backend Engineer

Responsibilities
- Maintain the billing API for our customers
- Respond to production incidents

Requirements
- PostgreSQL
- Docker
- Python
"""


async def test_job_specific_interview_prioritises_the_jobs_skills_and_duties(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    job = await client.post(
        JOBS, headers=headers, json={"title": "Backend Engineer", "description": JOB_WITH_DUTIES}
    )
    job_id = job.json()["id"]
    body = await started(
        client,
        headers,
        interview_types=["technical", "job_specific"],
        question_count=6,
        job_id=job_id,
        difficulty="intermediate",
    )
    assert body["job_id"] == job_id and body["job_title"] == "Backend Engineer"
    await answer_all(client, headers, body["id"])
    asked = (await client.get(f"{IV}/{body['id']}/questions", headers=headers)).json()
    technical = [q for q in asked if q["category"] == "technical"]
    job_specific = [q for q in asked if q["category"] == "job_specific"]
    assert len(technical) == len(job_specific) == 3
    tags = {t for q in technical for t in BANK_BY_TEXT[q["text"]].tags}
    assert {"sql", "containers", "python"} <= tags  # the job's skills come first
    duties = " ".join(q["text"] for q in job_specific)
    assert "Maintain the billing API" in duties and "Respond to production incidents" in duties


async def test_a_deleted_job_does_not_break_the_interview_or_its_report(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    job = await client.post(
        JOBS, headers=headers, json={"title": "Backend Engineer", "description": JOB_WITH_DUTIES}
    )
    body = await started(
        client, headers, interview_types=["job_specific"], question_count=2, job_id=job.json()["id"]
    )
    await client.delete(f"{JOBS}/{job.json()['id']}", headers=headers)
    await answer_all(client, headers, body["id"])
    report = (await client.post(f"{IV}/{body['id']}/complete", headers=headers)).json()["report"]
    assert report["job_title"] == "Backend Engineer"
    fetched = (await client.get(f"{IV}/{body['id']}", headers=headers)).json()
    assert fetched["job_id"] is None and fetched["job_title"] == "Backend Engineer"


# --------------------------------------------------------- answers & ordering


async def test_answers_must_target_the_current_question_once(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers, question_count=3))["id"]
    first = (await current(client, headers, sid))["question"]
    ok = await answer(client, headers, sid, first["id"])
    second = ok.json()["next_question"]

    repeat = await answer(client, headers, sid, first["id"])
    assert repeat.status_code == 409 and repeat.json()["error"]["code"] == "not_current_question"
    unknown = await answer(client, headers, sid, "11111111-1111-1111-1111-111111111111")
    assert unknown.status_code == 409
    assert (await current(client, headers, sid))["question"]["id"] == second["id"]
    assert len((await client.get(f"{IV}/{sid}/questions", headers=headers)).json()) == 2


async def test_each_question_is_answered_exactly_once_in_the_database(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    sid = (await started(client, headers, question_count=2))["id"]
    first = (await current(client, headers, sid))["question"]
    await answer(client, headers, sid, first["id"])
    await answer(client, headers, sid, first["id"])
    rows = (await session.execute(select(InterviewAnswer))).scalars().all()
    assert len(rows) == 1


async def test_concurrent_submissions_cannot_corrupt_progress(
    concurrent_client: httpx.AsyncClient,
) -> None:
    client = concurrent_client
    headers = await headers_for(client)
    sid = (await started(client, headers, question_count=3))["id"]
    first = (await current(client, headers, sid))["question"]

    responses = await asyncio.gather(
        *[answer(client, headers, sid, first["id"], f"Answer number {i}") for i in range(4)]
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409], codes
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} <= {
        "concurrent_submission",
        "not_current_question",
        "already_answered",
        "no_open_question",
    }
    asked = (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
    assert [q["main_index"] for q in asked] == [0, 1]  # advanced exactly once
    assert sum(1 for q in asked if q["answer"]) == 1
    progress = (await client.get(f"{IV}/{sid}", headers=headers)).json()["progress"]
    assert progress["answered"] == 1 and progress["main_questions_asked"] == 2


async def test_concurrent_start_requests_start_once(concurrent_client: httpx.AsyncClient) -> None:
    client = concurrent_client
    headers = await headers_for(client)
    sid = (await create(client, headers, question_count=3)).json()["id"]
    responses = await asyncio.gather(
        *[client.post(f"{IV}/{sid}/start", headers=headers) for _ in range(3)]
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    asked = (await client.get(f"{IV}/{sid}/questions", headers=headers)).json()
    assert len(asked) == 1
    all_questions = (await client.get(f"{IV}/{sid}", headers=headers)).json()["progress"]
    assert all_questions["main_questions_total"] == 3


# ----------------------------------------------------------------- isolation


async def test_sessions_are_private_to_their_owner(client: httpx.AsyncClient) -> None:
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    sid = (await started(client, ada))["id"]
    question = (await current(client, ada, sid))["question"]
    await answer(client, ada, sid, question["id"])
    await client.post(f"{IV}/{sid}/complete", headers=ada)

    assert (await client.get(IV, headers=eve)).json() == []
    for method, path, kwargs in [
        ("GET", "", {}),
        ("POST", "/start", {}),
        ("POST", "/cancel", {}),
        ("POST", "/complete", {}),
        ("GET", "/current-question", {}),
        ("GET", "/questions", {}),
        ("GET", "/report", {}),
        ("GET", "/evaluations", {}),
        ("POST", "/answers", {"json": {"question_id": question["id"], "text": "stolen"}}),
    ]:
        options: dict[str, Any] = kwargs
        response = await client.request(method, f"{IV}/{sid}{path}", headers=eve, **options)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "interview_not_found"
    assert (await client.get(f"{IV}/{sid}/report", headers=ada)).status_code == 200


async def test_interview_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    for method, path in [
        ("POST", ""),
        ("GET", ""),
        ("GET", f"/{fake}"),
        ("POST", f"/{fake}/start"),
        ("POST", f"/{fake}/cancel"),
        ("POST", f"/{fake}/complete"),
        ("GET", f"/{fake}/current-question"),
        ("POST", f"/{fake}/answers"),
        ("GET", f"/{fake}/questions"),
        ("GET", f"/{fake}/report"),
        ("GET", f"/{fake}/evaluations"),
    ]:
        assert (await client.request(method, f"{IV}{path}")).status_code == 401, (method, path)


async def test_app_fixture_is_usable(app: FastAPI) -> None:
    assert app.state.llm_provider.available is False
