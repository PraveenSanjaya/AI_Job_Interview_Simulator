"""Candidate-to-job matching API: sources, history, isolation, privacy."""

import json
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import JobMatch
from tests.fakes import FakeLLMProvider
from tests.helpers import bearer, register_and_login
from tests.samples_jobs import BACKEND_JOB, INJECTION_JOB
from tests.test_resume_analysis_api import analyze as analyze_resume
from tests.test_resume_analysis_api import upload_resume

pytestmark = pytest.mark.anyio

JOBS = "/api/v1/jobs"
PROFILE = "/api/v1/profile"
INTEG = "/api/v1/integrations"

PROFILE_BODY: dict[str, Any] = {
    "full_name": "Ada Lovelace",
    "experience_level": "mid",
    "preferred_roles": ["Backend Developer"],
    "education": [{"institution": "SLIIT", "degree": "BSc (Hons) IT"}],
    "work_experience": [
        {
            "company": "Acme",
            "title": "Backend Engineer",
            "start_date": "2019-01-01",
            "is_current": True,
            "description": "Built REST APIs with Python.",
        }
    ],
    "skills": [
        {"name": "Python", "category": "technical"},
        {"name": "Docker", "category": "technical"},
        {"name": "Communication", "category": "soft"},
    ],
    "projects": [
        {
            "name": "Orders API",
            "description": "REST API deployed on AWS",
            "technologies": ["FastAPI", "PostgreSQL"],
        }
    ],
}


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def set_profile(client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any) -> None:
    response = await client.put(PROFILE, headers=headers, json={**PROFILE_BODY, **overrides})
    assert response.status_code == 200, response.text


async def make_job(
    client: httpx.AsyncClient, headers: dict[str, str], text: str = BACKEND_JOB, **extra: Any
) -> str:
    response = await client.post(
        JOBS,
        headers=headers,
        json={"title": "Senior Backend Engineer", "company": "Acme Payments", "description": text}
        | extra,
    )
    assert response.status_code == 201, response.text
    job_id: str = response.json()["id"]
    return job_id


async def run_match(
    client: httpx.AsyncClient, headers: dict[str, str], job_id: str, **body: Any
) -> httpx.Response:
    return await client.post(f"{JOBS}/{job_id}/match", headers=headers, json=body)


async def connect_github_and_portfolio(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    assert (
        await client.post(f"{INTEG}/github", headers=headers, json={"username": "janedoe"})
    ).status_code == 200
    assert (
        await client.post(
            f"{INTEG}/portfolio", headers=headers, json={"url": "https://jane.example/"}
        )
    ).status_code == 200


async def analysed_resume(app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    app.state.llm_provider = FakeLLMProvider()
    resume_id = await upload_resume(client, headers)
    assert (await analyze_resume(client, headers, resume_id)).status_code == 200
    return resume_id


def skill(report: dict[str, Any], name: str) -> dict[str, Any]:
    items = report["required_skills"]["items"] + report["preferred_skills"]["items"]
    return next(i for i in items if i["name"] == name)


# ------------------------------------------------------------------ basics


async def test_match_works_with_profile_only_and_no_ai_at_all(client: httpx.AsyncClient) -> None:
    """No AI provider is configured in this app: the deterministic match still works."""
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    response = await run_match(client, headers, job_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["job_id"] == job_id
    assert isinstance(body["overall_score"], int) and 0 <= body["overall_score"] <= 100
    report = body["report"]
    assert report["score"]["score"] == body["overall_score"]
    assert report["score"]["explanation"].startswith(f"{body['overall_score']}/100 = ")
    assert body["ai_advice"] is None and body["ai_provider"] is None
    assert skill(report, "Python")["status"] == "supported"
    assert skill(report, "Docker")["status"] == "weakly_supported"
    assert skill(report, "PostgreSQL")["status"] == "supported"  # project technologies
    assert "Terraform" in report["missing_requirements"]
    assert report["sources"] == {
        "profile": True,
        "resume": False,
        "github": False,
        "portfolio": False,
        "not_available": {
            "resume": "no analysed resume",
            "github": "not connected",
            "portfolio": "not connected",
        },
    }
    assert body["scoring_config"]["weights"]["required_skills"] == 0.4
    assert "no score guarantees" in report["disclaimer"]


async def test_match_can_be_listed_and_fetched(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    first = (await run_match(client, headers, job_id)).json()
    second = (await run_match(client, headers, job_id)).json()

    listing = (await client.get(f"{JOBS}/{job_id}/matches", headers=headers)).json()
    assert [m["id"] for m in listing] == [second["id"], first["id"]] or {
        m["id"] for m in listing
    } == {first["id"], second["id"]}
    assert all(m["score_status"] == "scored" for m in listing)
    assert listing[0].keys() == {
        "id",
        "job_id",
        "created_at",
        "overall_score",
        "score_status",
        "confidence",
    }

    fetched = await client.get(f"{JOBS}/{job_id}/matches/{first['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == first


async def test_uses_every_available_source_and_cites_them(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    await analysed_resume(app, client, headers)
    await connect_github_and_portfolio(client, headers)
    posting = "We are hiring a web developer.\n\nRequirements\n- Python\n- FastAPI\n- React\n"
    job_id = await make_job(client, headers, posting)

    report = (await run_match(client, headers, job_id)).json()["report"]
    assert (
        report["sources"]["resume"]
        and report["sources"]["github"]
        and report["sources"]["portfolio"]
    )
    assert report["sources"]["not_available"] == {}
    assert report["score"]["confidence"] == "high"
    fastapi = skill(report, "FastAPI")
    assert fastapi["status"] == "supported"
    assert {e["source"] for e in fastapi["evidence"]} >= {"profile", "github"}
    assert set(report["evidence_by_source"]) == {"profile", "resume", "github", "portfolio"}
    assert report["evidence_by_source"]["github"]
    react = skill(report, "React")
    assert react["status"] == "supported"  # described in the GitHub repo and portfolio page


async def test_explicit_source_selection(app: FastAPI, client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    await analysed_resume(app, client, headers)
    await connect_github_and_portfolio(client, headers)
    job_id = await make_job(client, headers)
    report = (await run_match(client, headers, job_id, include=["github"])).json()["report"]
    assert report["sources"]["github"] is True
    assert report["sources"]["resume"] is False and report["sources"]["portfolio"] is False
    assert report["sources"]["not_available"]["resume"] == "excluded by request"
    used = (await run_match(client, headers, job_id, include=["github"])).json()["evidence_used"]
    assert used["sources_used"] == ["profile", "github"]


async def test_naming_an_unavailable_source_is_an_error(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    github = await run_match(client, headers, job_id, include=["github"])
    assert github.status_code == 404
    assert github.json()["error"]["code"] == "source_not_connected"
    resume = await run_match(client, headers, job_id, include=["resume"])
    assert resume.status_code == 409
    assert resume.json()["error"]["code"] == "resume_not_analyzed"


async def test_resume_selection_is_validated_and_owned(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    await set_profile(client, ada)
    resume_id = await analysed_resume(app, client, ada)
    job_id = await make_job(client, ada)
    eve_job = await make_job(client, eve)

    stolen = await run_match(client, eve, eve_job, resume_id=resume_id)
    assert stolen.status_code == 404
    assert stolen.json()["error"]["code"] == "resume_not_found"

    unanalysed = await upload_resume(client, ada)
    pending = await run_match(client, ada, job_id, resume_id=unanalysed)
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "resume_not_analyzed"

    ok = await run_match(client, ada, job_id, resume_id=resume_id)
    assert ok.status_code == 201
    assert ok.json()["evidence_used"]["resume"]["resume_id"] == resume_id


async def test_candidate_with_no_data_gets_an_honest_unscored_report(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)  # registration creates an empty profile
    job_id = await make_job(client, headers)
    response = await run_match(client, headers, job_id)
    assert response.status_code == 201
    body = response.json()
    assert body["overall_score"] is None
    assert body["report"]["score"]["status"] == "insufficient_evidence"
    assert body["report"]["missing_requirements"] == []
    assert body["report"]["unverifiable_requirements"]
    listing = (await client.get(f"{JOBS}/{job_id}/matches", headers=headers)).json()
    assert listing[0]["overall_score"] is None
    assert listing[0]["score_status"] == "insufficient_evidence"


async def test_a_failed_job_cannot_be_matched(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(title: str, description: str) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr("app.services.jobs.parse_job", boom)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await run_match(client, headers, job_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_analyzed"


async def test_instructions_in_the_job_text_do_not_inflate_the_match(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    await set_profile(
        client,
        headers,
        skills=[{"name": "Rust", "category": "technical"}],
        projects=[],
        work_experience=[],
    )
    job_id = await make_job(client, headers, INJECTION_JOB)
    body = (await run_match(client, headers, job_id)).json()
    assert skill(body["report"], "Python")["status"] == "not_found"
    assert body["overall_score"] == 0


# ------------------------------------------------------------------ weights


async def test_request_weights_are_applied_and_recorded(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    default = (await run_match(client, headers, job_id)).json()
    zero = dict.fromkeys(default["scoring_config"]["weights"], 0) | {"required_skills": 1}
    custom = (await run_match(client, headers, job_id, weights=zero)).json()
    assert custom["scoring_config"]["weights"]["required_skills"] == 1
    assert custom["scoring_config"]["weights"]["education"] == 0
    only_required = custom["report"]["required_skills"]["coverage"]
    assert custom["overall_score"] == round(only_required * 100)
    assert custom["overall_score"] != default["overall_score"]
    # The defaults of the first match are untouched in its own record.
    assert (await client.get(f"{JOBS}/{job_id}/matches/{default['id']}", headers=headers)).json()[
        "scoring_config"
    ] == default["scoring_config"]


@pytest.mark.parametrize(
    "weights",
    [{"nonsense": 1}, {"required_skills": -1}, {"required_skills": "high"}, {}],
)
async def test_invalid_weights_are_rejected_before_anything_is_stored(
    client: httpx.AsyncClient, session: AsyncSession, weights: dict[str, Any]
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    response = await run_match(client, headers, job_id, weights=weights)
    if weights == {}:
        assert response.status_code == 201  # no overrides: defaults
        return
    assert response.status_code == 422
    assert (await session.execute(select(func.count()).select_from(JobMatch))).scalar_one() == 0


async def test_all_zero_weights_are_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    zero = dict.fromkeys(("required_skills", "preferred_skills", "experience", "education", "project_relevance", "technology_alignment", "evidence_strength"), 0)  # fmt: skip
    response = await run_match(client, headers, job_id, weights=zero)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_scoring_weights"


async def test_server_configured_weights_are_the_default(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    settings.match_weights = {"required_skills": 0.9, "education": 0.0}
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    body = (await run_match(client, headers, job_id)).json()
    assert body["scoring_config"]["weights"]["required_skills"] == 0.9
    assert body["scoring_config"]["weights"]["education"] == 0.0
    override = (await run_match(client, headers, job_id, weights={"required_skills": 0.1})).json()
    assert override["scoring_config"]["weights"]["required_skills"] == 0.1
    assert override["scoring_config"]["weights"]["education"] == 0.0


# --------------------------------------------------------- historical records


async def test_old_matches_do_not_change_when_candidate_data_or_job_changes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    resume_id = await analysed_resume(app, client, headers)
    await connect_github_and_portfolio(client, headers)
    job_id = await make_job(client, headers)
    original = (await run_match(client, headers, job_id)).json()
    assert original["evidence_used"]["resume"]["resume_id"] == resume_id

    # Change everything the match was built from.
    await set_profile(
        client,
        headers,
        skills=[
            {"name": "Terraform", "category": "technical"},
            {"name": "AWS", "category": "technical"},
        ],
        projects=[],
        work_experience=[],
    )
    assert (await client.delete(f"/api/v1/resumes/{resume_id}", headers=headers)).status_code == 204
    assert (await client.delete(f"{INTEG}/github", headers=headers)).status_code == 204
    assert (await client.delete(f"{INTEG}/portfolio", headers=headers)).status_code == 204
    changed = await client.put(
        f"{JOBS}/{job_id}",
        headers=headers,
        json={"description": "We are hiring a systems developer.\n\nRequirements\n- Rust\n"},
    )
    assert changed.status_code == 200

    unchanged = (
        await client.get(f"{JOBS}/{job_id}/matches/{original['id']}", headers=headers)
    ).json()
    assert unchanged == original
    assert unchanged["report"]["sources"]["github"] is True

    fresh = (await run_match(client, headers, job_id)).json()
    assert fresh["id"] != original["id"]
    assert fresh["report"]["sources"]["github"] is False
    assert (
        fresh["evidence_used"]["job"]["description_sha256"]
        != (original["evidence_used"]["job"]["description_sha256"])
    )
    assert len((await client.get(f"{JOBS}/{job_id}/matches", headers=headers)).json()) == 2


async def test_evidence_used_identifies_inputs_without_copying_personal_data(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    await analysed_resume(app, client, headers)
    await connect_github_and_portfolio(client, headers)
    job_id = await make_job(client, headers)
    body = (await run_match(client, headers, job_id)).json()
    used = body["evidence_used"]
    assert used["profile"]["skills"] == 3 and used["profile"]["updated_at"]
    assert used["github"]["login"] == "janedoe" and used["github"]["fetched_at"]
    assert used["portfolio"]["url"] == "https://jane.example/"
    assert used["job"]["analysis_parser"] == "deterministic"
    assert used["sources_used"] == ["profile", "resume", "github", "portfolio"]

    stored = (await session.execute(select(JobMatch))).scalar_one()
    blob = json.dumps([stored.evidence_used, stored.result, stored.scoring_config])
    for private in ("ada@example.com", "jane.doe@example.com", "+94 77 123 4567"):
        assert private not in blob


async def test_matching_never_logs_candidate_or_job_text(
    app: FastAPI, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    await analysed_resume(app, client, headers)
    job_id = await make_job(client, headers)
    caplog.set_level(logging.DEBUG)
    await run_match(client, headers, job_id)
    for text in (
        "jane.doe@example.com",
        "Orders API",
        "Strong proficiency in Python",
        "Ada Lovelace",
    ):
        assert text not in caplog.text


# ---------------------------------------------------------------- isolation


async def test_matches_are_private_to_their_owner(client: httpx.AsyncClient) -> None:
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    await set_profile(client, ada)
    job_id = await make_job(client, ada)
    match_id = (await run_match(client, ada, job_id)).json()["id"]

    for method, path in [
        ("POST", f"{JOBS}/{job_id}/match"),
        ("GET", f"{JOBS}/{job_id}/matches"),
        ("GET", f"{JOBS}/{job_id}/matches/{match_id}"),
    ]:
        response = await client.request(
            method, path, headers=eve, json={} if method == "POST" else None
        )
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "job_not_found"

    # A match id from another job of the same user is not found either.
    other_job = await make_job(client, ada, title="Other") if False else await make_job(client, ada)
    wrong = await client.get(f"{JOBS}/{other_job}/matches/{match_id}", headers=ada)
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "match_not_found"
    assert (await client.get(f"{JOBS}/{job_id}/matches", headers=ada)).status_code == 200


async def test_matching_requires_authentication(client: httpx.AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    for method, path in [
        ("POST", f"{JOBS}/{fake}/match"),
        ("GET", f"{JOBS}/{fake}/matches"),
        ("GET", f"{JOBS}/{fake}/matches/{fake}"),
    ]:
        assert (await client.request(method, path)).status_code == 401


async def test_deleting_a_job_deletes_its_matches(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    await set_profile(client, headers)
    job_id = await make_job(client, headers)
    await run_match(client, headers, job_id)
    assert (await client.delete(f"{JOBS}/{job_id}", headers=headers)).status_code == 204
    assert (await session.execute(select(func.count()).select_from(JobMatch))).scalar_one() == 0


async def test_unknown_request_fields_are_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    assert (await run_match(client, headers, job_id, score=100)).status_code == 422
    assert (await run_match(client, headers, job_id, include=["linkedin"])).status_code == 422
