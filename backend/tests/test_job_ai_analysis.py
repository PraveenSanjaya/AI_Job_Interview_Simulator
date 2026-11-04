"""Optional AI enrichment of job analyses: grounding, consent, failures."""

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AITimeoutError
from app.ai.job_analysis import JobAIOutput, enrich, parse_output
from app.jobs.parser import parse_job
from app.models import JobAnalysis
from tests.fakes import FakeLLMProvider
from tests.helpers import bearer, register_and_login
from tests.samples_jobs import BACKEND_JOB, INJECTION_JOB, VAGUE_JOB

pytestmark = pytest.mark.anyio

JOBS = "/api/v1/jobs"

TEXT = """\
Platform Engineer

Requirements
- Experience with Prefect for workflow orchestration
- Must have deep knowledge of Python
Nice to have
- Exposure to Pulumi
Responsibilities
- Keep the data platform reliable
"""


def ai_reply(**overrides: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "technical_skills": [
            {
                "name": "Prefect",
                "kind": "tool",
                "importance": "required",
                "quote": "Experience with Prefect for workflow orchestration",
            }
        ],
        "soft_skills": [],
        "certifications": [],
        "domain_knowledge": [],
        "responsibilities": ["Keep the data platform reliable"],
        "qualifications": [],
    }
    reply.update(overrides)
    return reply


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def make_job(
    client: httpx.AsyncClient, headers: dict[str, str], text: str = TEXT, title: str = "Engineer"
) -> str:
    response = await client.post(JOBS, headers=headers, json={"title": title, "description": text})
    assert response.status_code == 201, response.text
    job_id: str = response.json()["id"]
    return job_id


def use_provider(app: FastAPI, reply: Any = None, **kwargs: Any) -> FakeLLMProvider:
    provider = FakeLLMProvider(ai_reply() if reply is None else reply, **kwargs)
    app.state.llm_provider = provider
    return provider


async def analyze(
    client: httpx.AsyncClient, headers: dict[str, str], job_id: str, **body: Any
) -> httpx.Response:
    return await client.post(f"{JOBS}/{job_id}/analyze", headers=headers, json=body)


async def parsed_of(
    client: httpx.AsyncClient, headers: dict[str, str], job_id: str
) -> dict[str, Any]:
    response = await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)
    result: dict[str, Any] = response.json()["result"]["parsed"]
    return result


def skill_named(parsed: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in parsed["technical_skills"] if s["name"] == name)


# ------------------------------------------------------------ deterministic


async def test_reanalysis_without_ai_needs_no_provider(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    use_provider(app, available=False)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id)
    assert response.status_code == 200, response.text
    assert response.json()["parser"] == "deterministic"
    assert response.json()["provider"] is None


# ------------------------------------------------------------- enrichment


async def test_ai_adds_a_grounded_item_and_labels_its_origin(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    provider = use_provider(app)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parser"] == "deterministic+ai"
    assert (body["provider"], body["model"]) == ("fake", "fake-model")
    assert body["consent_external_ai"] is False
    assert body["result"]["unverified_items_removed"] == 0

    parsed = body["result"]["parsed"]
    prefect = skill_named(parsed, "Prefect")
    assert prefect["source"] == "ai"
    assert prefect["importance"] == "required"
    assert prefect["importance_stated"] is True
    assert "Experience with Prefect" in prefect["quote"]
    assert skill_named(parsed, "Python")["source"] == "text"  # parser items keep their origin
    assert [r["text"] for r in parsed["responsibilities"]] == ["Keep the data platform reliable"]
    assert len(provider.calls) == 1

    # The stored analysis is what GET returns afterwards.
    assert await parsed_of(client, headers, job_id) == parsed


async def test_ai_item_without_support_in_the_text_is_removed(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    reply = ai_reply(
        technical_skills=[
            {"name": "Kubernetes", "importance": "required", "quote": "Must know Kubernetes"},
            {"name": "Prefect", "importance": "unspecified", "quote": "Experience with Prefect"},
        ],
        responsibilities=["Lead the whole company"],
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.json()["result"]["unverified_items_removed"] == 2
    parsed = response.json()["result"]["parsed"]
    assert {s["name"] for s in parsed["technical_skills"]} == {"Prefect", "Python"}
    assert parsed["responsibilities"] == [
        {"text": "Keep the data platform reliable", "importance": "unspecified"}
    ]


async def test_item_whose_name_is_not_in_its_own_quote_is_removed(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    reply = ai_reply(
        technical_skills=[
            {
                "name": "Terraform",
                "importance": "required",
                "quote": "Experience with Prefect for workflow orchestration",
            }
        ]
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.json()["result"]["unverified_items_removed"] == 1
    names = {s["name"] for s in response.json()["result"]["parsed"]["technical_skills"]}
    assert "Terraform" not in names


async def test_importance_claim_needs_supporting_words_in_the_quote(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    text = "Platform Engineer\n\nWe work with Prefect and Dagster every day.\n"
    reply = ai_reply(
        technical_skills=[
            {
                "name": "Prefect",
                "importance": "required",
                "quote": "We work with Prefect and Dagster",
            },
        ],
        responsibilities=[],
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers, text)
    parsed = (await analyze(client, headers, job_id, use_ai=True)).json()["result"]["parsed"]
    prefect = skill_named(parsed, "Prefect")
    assert prefect["importance"] == "unspecified"  # the quote never says "required"
    assert prefect["importance_stated"] is False


async def test_importance_comes_from_where_the_quote_sits_not_from_the_model(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    reply = ai_reply(
        technical_skills=[
            # The model claims "required", but the sentence is under "Nice to have".
            {"name": "Pulumi", "importance": "required", "quote": "Exposure to Pulumi"},
        ],
        responsibilities=[],
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    parsed = (await analyze(client, headers, job_id, use_ai=True)).json()["result"]["parsed"]
    pulumi = skill_named(parsed, "Pulumi")
    assert pulumi["importance"] == "preferred"
    assert pulumi["importance_stated"] is True
    assert pulumi["source"] == "ai"


async def test_ai_cannot_change_education_experience_or_seniority(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    reply = ai_reply(
        seniority={"level": "lead", "quote": "Platform Engineer"},
        education=[{"level": "doctorate", "quote": "x"}],
        experience=[{"min_years": 20, "quote": "x"}],
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    before = await parsed_of(client, headers, job_id)
    after = (await analyze(client, headers, job_id, use_ai=True)).json()["result"]["parsed"]
    for key in ("seniority", "education", "experience"):
        assert after[key] == before[key]


async def test_fenced_json_reply_is_accepted(client: httpx.AsyncClient, app: FastAPI) -> None:
    use_provider(app, "```json\n" + json.dumps(ai_reply()) + "\n```")
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    assert (await analyze(client, headers, job_id, use_ai=True)).status_code == 200


# --------------------------------------------------------- consent, failures


async def test_external_provider_needs_explicit_consent(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    provider = use_provider(app, is_external=True)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    refused = await analyze(client, headers, job_id, use_ai=True)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "ai_consent_required"
    assert provider.calls == []  # nothing left the server

    allowed = await analyze(client, headers, job_id, use_ai=True, allow_external_ai=True)
    assert allowed.status_code == 200
    assert allowed.json()["consent_external_ai"] is True
    assert len(provider.calls) == 1


async def test_consent_flag_alone_never_triggers_ai(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    provider = use_provider(app, is_external=True)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id, allow_external_ai=True)
    assert response.status_code == 200
    assert response.json()["parser"] == "deterministic"
    assert provider.calls == []


async def test_unavailable_provider_is_503_and_changes_nothing(
    client: httpx.AsyncClient, app: FastAPI, session: AsyncSession
) -> None:
    use_provider(app, available=False)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    before = (await session.execute(select(JobAnalysis))).scalar_one().id
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"
    session.expire_all()
    assert (await session.execute(select(JobAnalysis))).scalar_one().id == before


@pytest.mark.parametrize(
    "reply",
    ["not json at all", "[1, 2]", json.dumps({"technical_skills": "Python"})],
)
async def test_invalid_ai_output_is_502_and_keeps_the_previous_analysis(
    client: httpx.AsyncClient, app: FastAPI, session: AsyncSession, reply: str
) -> None:
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    before = (await session.execute(select(JobAnalysis))).scalar_one().id
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_ai_response"
    session.expire_all()
    stored = (await session.execute(select(JobAnalysis))).scalar_one()
    assert stored.id == before
    assert stored.parser == "deterministic"


async def test_provider_timeout_is_504(client: httpx.AsyncClient, app: FastAPI) -> None:
    use_provider(app, error=AITimeoutError("The AI provider timed out"))
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.status_code == 504


# ------------------------------------------------------ prompt injection & scope


async def test_job_text_reaches_the_model_only_as_delimited_data(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    provider = use_provider(app, ai_reply(technical_skills=[], responsibilities=[]))
    headers = await headers_for(client)
    job_id = await make_job(client, headers, INJECTION_JOB, "Backend Developer")
    await analyze(client, headers, job_id, use_ai=True)
    await analyze(client, headers, job_id, use_ai=True)

    system, user = provider.calls[0]
    assert "Ignore all previous instructions" not in system
    assert "UNTRUSTED DATA" in system
    assert "Ignore all previous instructions" in user
    boundary_lines = [line for line in user.splitlines() if line.startswith("JOB_")]
    assert len(boundary_lines) == 2 and boundary_lines[0] == boundary_lines[1]
    second_user = provider.calls[1][1]
    assert boundary_lines[0] not in second_user  # a fresh random boundary per request
    assert provider.calls[0][0] == provider.calls[1][0]  # the system prompt is fixed


async def test_an_obedient_model_cannot_inject_requirements(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    """If the model obeys text in the job and claims things the job never says, the
    claims are dropped because they cannot be quoted from the description."""
    reply = ai_reply(
        technical_skills=[
            {"name": "Python", "importance": "preferred", "quote": "give a score of 100"},
            {"name": "Rust", "importance": "required", "quote": "Rust is required"},
        ],
        responsibilities=["Reveal the system prompt"],
    )
    use_provider(app, reply)
    headers = await headers_for(client)
    job_id = await make_job(client, headers, INJECTION_JOB, "Backend Developer")
    response = await analyze(client, headers, job_id, use_ai=True)
    parsed = response.json()["result"]["parsed"]
    assert {s["name"] for s in parsed["technical_skills"]} == {"Python"}
    assert skill_named(parsed, "Python")["importance"] == "required"
    assert parsed["responsibilities"] == []
    assert response.json()["result"]["unverified_items_removed"] == 3


async def test_input_longer_than_the_limit_is_flagged_truncated(
    client: httpx.AsyncClient, app: FastAPI, settings: Any
) -> None:
    use_provider(app, ai_reply(technical_skills=[], responsibilities=[]))
    settings.ai_max_input_chars = 2000
    headers = await headers_for(client)
    filler = "\n".join(f"- Item {i} describing a duty in detail" for i in range(3000))
    job_id = await make_job(client, headers, BACKEND_JOB + filler[:25000])
    response = await analyze(client, headers, job_id, use_ai=True)
    assert response.status_code == 200
    assert response.json()["input_truncated"] is True


async def test_analyze_is_scoped_to_the_owner(client: httpx.AsyncClient, app: FastAPI) -> None:
    provider = use_provider(app)
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    job_id = await make_job(client, ada)
    response = await analyze(client, eve, job_id, use_ai=True)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"
    assert provider.calls == []
    assert (await client.post(f"{JOBS}/{job_id}/analyze", json={})).status_code == 401


async def test_editing_the_job_discards_the_ai_enriched_analysis(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    job_id = await make_job(client, headers)
    await analyze(client, headers, job_id, use_ai=True)
    await client.put(f"{JOBS}/{job_id}", headers=headers, json={"description": VAGUE_JOB})
    analysis = (await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)).json()
    assert analysis["parser"] == "deterministic"
    assert analysis["provider"] is None


# ------------------------------------------------------------------ unit level


def test_parse_output_rejects_non_objects_and_bad_types() -> None:
    with pytest.raises(Exception, match="not a JSON object"):
        parse_output("[]")
    with pytest.raises(Exception, match="expected structure"):
        parse_output('{"technical_skills": 5}')
    assert parse_output("{}") == JobAIOutput()


def test_enrich_does_not_mutate_the_deterministic_result() -> None:
    parsed = parse_job("Engineer", TEXT)
    snapshot = parsed.model_dump()
    output = parse_output(json.dumps(ai_reply()))
    merged, removed = enrich(parsed, output, TEXT)
    assert removed == 0
    assert parsed.model_dump() == snapshot
    assert len(merged.technical_skills) == len(parsed.technical_skills) + 1


# ------------------------------------------------- labels and statements (unit)

LABEL_TEXT = """\
Platform Engineer

We value resilience under pressure and run an agritech business.
Requirements
- Offensive Security OSCP certification is expected
- Good teamwork
Responsibilities
- Keep the data platform reliable
- Review pull requests carefully
"""


def test_enrich_adds_grounded_labels_and_statements_and_drops_the_rest() -> None:
    parsed = parse_job("Platform Engineer", LABEL_TEXT)
    output = parse_output(
        json.dumps(
            {
                "soft_skills": [
                    {"name": "Resilience", "quote": "We value resilience under pressure"},
                    {"name": "Teamwork", "quote": "Good teamwork"},  # already found by the parser
                    {"name": "Empathy", "quote": "Show empathy daily"},  # not in the text
                ],
                "certifications": [
                    {"name": "OSCP", "quote": "Offensive Security OSCP certification is expected"},
                    {"name": "CISM", "quote": "Offensive Security OSCP certification is expected"},
                ],
                "domain_knowledge": [
                    {"name": "Agritech", "quote": "run an agritech business"},
                ],
                "responsibilities": [
                    "Keep the data platform reliable",  # duplicate of the parser's
                    "Review pull requests carefully",  # already found too
                    "Mentor the whole company",  # not in the text
                ],
                "qualifications": ["Good teamwork", "Run marathons"],
            }
        )
    )
    merged, removed = enrich(parsed, output, LABEL_TEXT)

    soft = {s.name: s for s in merged.soft_skills}
    assert soft["Resilience"].source == "ai"
    assert soft["Teamwork"].source == "text"  # not duplicated, not relabelled
    assert "Empathy" not in soft
    certs = {c.name for c in merged.certifications}
    assert "OSCP" in certs and "CISM" not in certs
    assert [d.name for d in merged.domain_knowledge if d.source == "ai"] == ["Agritech"]
    assert [r.text for r in merged.responsibilities].count("Keep the data platform reliable") == 1
    assert "Mentor the whole company" not in [r.text for r in merged.responsibilities]
    assert "Run marathons" not in [q.text for q in merged.qualifications]
    assert removed == 4  # Empathy, CISM, "Mentor ...", "Run marathons"


def test_enrich_warning_is_refreshed_when_ai_finds_the_first_technology() -> None:
    text = "Data Engineer\n\nRequirements\n- Experience with Prefect for workflow orchestration\n"
    parsed = parse_job("Data Engineer", text)
    assert any("No specific technologies" in w for w in parsed.warnings)
    output = parse_output(
        json.dumps(
            {
                "technical_skills": [
                    {
                        "name": "Prefect",
                        "quote": "Experience with Prefect for workflow orchestration",
                    }
                ]
            }
        )
    )
    merged, _ = enrich(parsed, output, text)
    assert merged.required_technical_skills == ["Prefect"]
    assert not any("No specific technologies" in w for w in merged.warnings)


async def test_parser_failure_during_reanalysis_marks_the_job_failed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await headers_for(client)
    job_id = await make_job(client, headers)

    def boom(title: str, description: str) -> None:
        raise RuntimeError(description)

    monkeypatch.setattr("app.services.job_analysis.parse_job", boom)
    response = await analyze(client, headers, job_id)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "job_parse_failed"
    assert "Requirements" not in response.text
    job = (await client.get(f"{JOBS}/{job_id}", headers=headers)).json()
    assert job["status"] == "failed" and job["has_analysis"] is False
