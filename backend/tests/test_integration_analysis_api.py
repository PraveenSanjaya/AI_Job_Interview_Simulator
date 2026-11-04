import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIProviderError, AIRateLimitedError, AITimeoutError
from app.models import IntegrationAnalysis
from tests.fakes import SAMPLE_RESUME, FakeLLMProvider
from tests.helpers import bearer, register_and_login
from tests.samples import make_txt
from tests.test_integration_analysis import LONG_README, model_reply

pytestmark = pytest.mark.anyio

INTEG = "/api/v1/integrations"
ANALYSIS = f"{INTEG}/analysis"
PROFILE = "/api/v1/profile"


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def connect_sources(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str], *, portfolio: bool = True
) -> None:
    from tests.fakes_github import FakeGitHubClient

    app.state.github_client = FakeGitHubClient(readmes={"interview-sim": LONG_README})
    assert (
        await client.post(f"{INTEG}/github", headers=headers, json={"username": "janedoe"})
    ).status_code == 200
    if portfolio:
        response = await client.post(
            f"{INTEG}/portfolio", headers=headers, json={"url": "https://jane.example/"}
        )
        assert response.status_code == 200, response.text


def use_provider(app: FastAPI, reply: Any = None, **kwargs: Any) -> FakeLLMProvider:
    provider = FakeLLMProvider(model_reply() if reply is None else reply, **kwargs)
    app.state.llm_provider = provider
    return provider


async def analyze(
    client: httpx.AsyncClient, headers: dict[str, str], **body: Any
) -> httpx.Response:
    return await client.post(ANALYSIS, headers=headers, json=body)


async def count_analyses(session: AsyncSession) -> int:
    return (
        await session.execute(select(func.count()).select_from(IntegrationAnalysis))
    ).scalar_one()


# ------------------------------------------------------------------ happy path


async def test_analysis_combines_sources_and_separates_facts_from_opinions(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    provider = use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)

    response = await analyze(client, headers)
    assert response.status_code == 201, response.text
    body = response.json()
    facts, assessment = body["result"]["facts"], body["result"]["assessment"]
    assert facts["sources_used"] == ["github", "portfolio"]
    assert facts["github"]["login"] == "janedoe"
    assert facts["portfolio"]["pages"][0]["url"] == "https://jane.example/"
    assert assessment["project_assessments"][0]["source"] == {
        "source": "github",
        "ref": "interview-sim",
    }
    assert body["consent_external_ai"] is False and body["provider"] == "fake"
    assert len(provider.calls) == 1
    _, user = provider.calls[0]
    assert "janedoe" in user and "jane.example" in user and "Backend Developer" not in user
    assert await count_analyses(session) == 1

    assert (await client.get(f"{ANALYSIS}/{body['id']}", headers=headers)).json() == body
    listed = (await client.get(ANALYSIS, headers=headers)).json()
    assert listed[0]["id"] == body["id"] and listed[0]["sources_used"] == ["github", "portfolio"]


async def test_preferred_roles_from_the_profile_are_used_as_context(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    provider = use_provider(app)
    headers = await headers_for(client)
    await client.put(
        PROFILE, headers=headers, json={"full_name": "Ada", "preferred_roles": ["Data Engineer"]}
    )
    await connect_sources(app, client, headers, portfolio=False)
    await analyze(client, headers)
    assert "Data Engineer" in provider.calls[0][1]


async def test_a_single_source_can_be_selected(app: FastAPI, client: httpx.AsyncClient) -> None:
    provider = use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    body = (await analyze(client, headers, include=["portfolio"])).json()
    assert body["result"]["facts"]["sources_used"] == ["portfolio"]
    assert body["github_source_id"] is None and body["portfolio_source_id"]
    assert "janedoe" not in provider.calls[0][1]  # GitHub data was not sent


async def test_resume_facts_enable_cv_vs_public_evidence_comparison(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers, portfolio=False)

    # Analyse a resume with a separate fake provider run, then compare.
    from tests.fakes import good_model_output

    app.state.llm_provider = FakeLLMProvider(good_model_output())
    upload = await client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("cv.txt", make_txt(SAMPLE_RESUME.splitlines()))},
    )
    resume_id = upload.json()["id"]
    assert (
        await client.post(f"/api/v1/resumes/{resume_id}/analyze", headers=headers)
    ).status_code == 200

    use_provider(app)
    body = (await analyze(client, headers, resume_id=resume_id)).json()
    consistency = body["result"]["facts"]["consistency"]
    found = {i["skill"] for i in consistency["cv_skills_with_public_evidence"]}
    assert {"Python", "FastAPI", "PostgreSQL", "Docker"} & found
    assert "Teamwork" not in found
    assert body["resume_id"] == resume_id and "resume" in body["result"]["facts"]["sources_used"]


async def test_resume_must_exist_be_yours_and_be_analysed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    await connect_sources(app, client, ada, portfolio=False)

    missing = await analyze(client, ada, resume_id="00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "resume_not_found"

    upload = await client.post(
        "/api/v1/resumes", headers=bob, files={"file": ("cv.txt", make_txt(), "text/plain")}
    )
    stolen = await analyze(client, ada, resume_id=upload.json()["id"])
    assert stolen.status_code == 404  # Bob's resume looks like it does not exist

    own = await client.post(
        "/api/v1/resumes", headers=ada, files={"file": ("cv.txt", make_txt(), "text/plain")}
    )
    unanalysed = await analyze(client, ada, resume_id=own.json()["id"])
    assert unanalysed.status_code == 409
    assert unanalysed.json()["error"]["code"] == "resume_not_analyzed"


# ------------------------------------------------------------------ availability & consent


async def test_no_sources_connected_is_a_clear_conflict(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    provider = use_provider(app)
    headers = await headers_for(client)
    response = await analyze(client, headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_sources_connected"
    assert provider.calls == []


async def test_explicitly_requesting_an_unconnected_source_is_404(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers, portfolio=False)
    response = await analyze(client, headers, include=["portfolio"])
    assert (
        response.status_code == 404 and response.json()["error"]["code"] == "source_not_connected"
    )


async def test_application_works_without_an_ai_provider(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Default config: no provider. Sources still connect; analysis reports 503."""
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    response = await analyze(client, headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_unavailable"
    assert (await client.get(f"{INTEG}/github", headers=headers)).status_code == 200
    assert await count_analyses(session) == 0


async def test_external_provider_requires_explicit_consent(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    provider = use_provider(app, is_external=True)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)

    for body in ({}, {"allow_external_ai": False}):
        denied = await analyze(client, headers, **body)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "ai_consent_required"
    assert provider.calls == [] and await count_analyses(session) == 0

    allowed = await analyze(client, headers, allow_external_ai=True)
    assert allowed.status_code == 201 and allowed.json()["consent_external_ai"] is True
    assert len(provider.calls) == 1


async def test_consent_must_be_a_real_boolean_and_unknown_fields_are_rejected(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app, is_external=True)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    assert (await analyze(client, headers, allow_external_ai="yes please")).status_code == 422
    assert (await analyze(client, headers, include=["linkedin"])).status_code == 422
    assert (await analyze(client, headers, surprise=1)).status_code == 422


# ------------------------------------------------------------------ AI failures


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AITimeoutError("slow"), 504, "ai_timeout"),
        (AIRateLimitedError(20), 429, "ai_rate_limited"),
        (AIProviderError("down"), 502, "ai_provider_error"),
    ],
)
async def test_provider_failures_store_nothing_and_report_clean_errors(
    app: FastAPI,
    client: httpx.AsyncClient,
    session: AsyncSession,
    error: Exception,
    status: int,
    code: str,
) -> None:
    use_provider(app, error=error)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    response = await analyze(client, headers)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert await count_analyses(session) == 0


@pytest.mark.parametrize("reply", ["garbage", "[]", '{"assessment": {"strengths": "x"}}', ""])
async def test_invalid_ai_output_is_rejected_and_not_stored(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, reply: str
) -> None:
    use_provider(app, reply)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    response = await analyze(client, headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_ai_response"
    assert await count_analyses(session) == 0


async def test_unsupported_ai_claims_are_removed_before_storage(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    reply = model_reply()
    reply["assessment"]["demonstrated_skills"].append(
        {"name": "Kubernetes", "evidence": [{"source": "github", "ref": "interview-sim"}]}
    )
    reply["assessment"]["project_assessments"][0]["technologies_demonstrated"].append("Rust")
    use_provider(app, reply)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    body = (await analyze(client, headers)).json()
    assert body["result"]["unverified_items_removed"] == 2
    assert "Kubernetes" not in str(body["result"]["assessment"])
    assert "Rust" not in str(body["result"]["assessment"])


# ------------------------------------------------------------------ ownership & lifecycle


async def test_analyses_are_private_to_their_owner(app: FastAPI, client: httpx.AsyncClient) -> None:
    use_provider(app)
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    await connect_sources(app, client, ada)
    analysis_id = (await analyze(client, ada)).json()["id"]

    assert (await client.get(ANALYSIS, headers=bob)).json() == []
    for method, path, kwargs in (
        ("get", f"{ANALYSIS}/{analysis_id}", {}),
        ("delete", f"{ANALYSIS}/{analysis_id}", {}),
        ("post", f"{ANALYSIS}/{analysis_id}/apply-to-profile", {"json": {"headline": "x"}}),
    ):
        response = await getattr(client, method)(path, headers=bob, **kwargs)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "analysis_not_found"
    assert (await client.get(f"{ANALYSIS}/{analysis_id}", headers=ada)).status_code == 200
    assert (await client.get(PROFILE, headers=bob)).json()["headline"] is None


async def test_unauthenticated_requests_are_rejected(client: httpx.AsyncClient) -> None:
    zero = "00000000-0000-0000-0000-000000000000"
    assert (await client.post(ANALYSIS, json={})).status_code == 401
    assert (await client.get(ANALYSIS)).status_code == 401
    assert (await client.get(f"{ANALYSIS}/{zero}")).status_code == 401
    assert (await client.delete(f"{ANALYSIS}/{zero}")).status_code == 401
    assert (
        await client.post(f"{ANALYSIS}/{zero}/apply-to-profile", json={"headline": "x"})
    ).status_code == 401


async def test_disconnecting_a_source_deletes_analyses_derived_from_it(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    analysis_id = (await analyze(client, headers)).json()["id"]
    assert (await client.delete(f"{INTEG}/portfolio", headers=headers)).status_code == 204
    assert await count_analyses(session) == 0
    assert (await client.get(f"{ANALYSIS}/{analysis_id}", headers=headers)).status_code == 404


async def test_reconnecting_replaces_the_source_and_its_stale_analyses(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers, portfolio=False)
    await analyze(client, headers)
    await client.post(f"{INTEG}/github", headers=headers, json={"username": "janedoe"})
    assert await count_analyses(session) == 0  # derived from the replaced snapshot


async def test_deleting_an_analysis_keeps_the_sources(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    analysis_id = (await analyze(client, headers)).json()["id"]
    assert (await client.delete(f"{ANALYSIS}/{analysis_id}", headers=headers)).status_code == 204
    assert (await client.delete(f"{ANALYSIS}/{analysis_id}", headers=headers)).status_code == 404
    assert (await client.get(f"{INTEG}/github", headers=headers)).status_code == 200


async def test_analysis_is_rate_limited_per_user(app: FastAPI, client: httpx.AsyncClient) -> None:
    from app.core.rate_limit import InMemoryRateLimiter

    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    codes = [(await analyze(client, headers)).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


# ------------------------------------------------------------------ profile approval


async def test_analysis_offers_a_suggestion_but_changes_nothing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    before = (await client.get(PROFILE, headers=headers)).json()
    body = (await analyze(client, headers)).json()

    suggestion = body["profile_suggestion"]
    assert [p["name"] for p in suggestion["projects"]] == ["interview-sim"]  # has a description
    assert suggestion["projects"][0]["url"] == "https://github.com/janedoe/interview-sim"
    assert suggestion["projects"][0]["technologies"][0] == "Python"
    names = {s["name"] for s in suggestion["skills"]}
    assert {"Python", "Shell", "FastAPI"} <= names
    assert (await client.get(PROFILE, headers=headers)).json() == before  # untouched


async def test_only_user_approved_data_reaches_the_profile(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    body = (await analyze(client, headers)).json()

    selected = {
        "skills": [s for s in body["profile_suggestion"]["skills"] if s["name"] == "Python"]
    }
    response = await client.post(
        f"{ANALYSIS}/{body['id']}/apply-to-profile", headers=headers, json=selected
    )
    assert response.status_code == 200 and response.json()["applied"] == {"skills": 1}
    profile = (await client.get(PROFILE, headers=headers)).json()
    assert [s["name"] for s in profile["skills"]] == ["Python"]
    assert profile["projects"] == []  # suggested but not approved: not applied


async def test_existing_profile_data_is_preserved_when_applying(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await client.put(
        PROFILE,
        headers=headers,
        json={
            "full_name": "Ada Lovelace",
            "headline": "My headline",
            "skills": [{"name": "python", "category": "technical", "proficiency": "expert"}],
            "projects": [{"name": "My own project", "description": "mine"}],
        },
    )
    await connect_sources(app, client, headers)
    body = (await analyze(client, headers)).json()
    result = await client.post(
        f"{ANALYSIS}/{body['id']}/apply-to-profile",
        headers=headers,
        json={**body["profile_suggestion"], "headline": "Overwrite attempt"},
    )
    profile = result.json()["profile"]
    assert profile["headline"] == "My headline"
    assert {
        "field": "headline",
        "reason": "profile already has a different value",
    } in result.json()["skipped"]
    assert [s["name"] for s in profile["skills"] if s["name"].lower() == "python"] == ["python"]
    assert profile["skills"][0]["proficiency"] == "expert"
    assert [p["name"] for p in profile["projects"]] == ["My own project", "interview-sim"]


@pytest.mark.parametrize(
    "payload", [{}, {"surprise": 1}, {"skills": [{"name": "Go", "category": "x"}]}]
)
async def test_invalid_apply_requests_are_rejected(
    app: FastAPI, client: httpx.AsyncClient, payload: dict[str, Any]
) -> None:
    use_provider(app)
    headers = await headers_for(client)
    await connect_sources(app, client, headers)
    analysis_id = (await analyze(client, headers)).json()["id"]
    response = await client.post(
        f"{ANALYSIS}/{analysis_id}/apply-to-profile", headers=headers, json=payload
    )
    assert response.status_code == 422


# ------------------------------------------------------------------ privacy


async def test_source_content_never_appears_in_logs_or_error_bodies(
    app: FastAPI, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    use_provider(app, "not json", is_external=True)
    headers = await headers_for(client)
    with caplog.at_level(logging.DEBUG):
        await connect_sources(app, client, headers)
        denied = await analyze(client, headers)
        failed = await analyze(client, headers, allow_external_ai=True)
    logged = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    for secret in (
        "Backend engineer. Python and FastAPI.",
        "jane.doe@example.com",
        "FastAPI, PostgreSQL",
    ):
        assert secret not in logged
        assert secret not in denied.text and secret not in failed.text
