"""Job description management API."""

import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobAnalysis, JobDescription
from tests.fakes_portfolio import FakeWeb
from tests.helpers import bearer, register_and_login
from tests.samples_jobs import BACKEND_JOB, VAGUE_JOB

pytestmark = pytest.mark.anyio

JOBS = "/api/v1/jobs"
POSTING = f"<html><head><title>Backend Engineer</title></head><body><h1>Backend Engineer</h1><p>{BACKEND_JOB.replace(chr(10), '</p><p>')}</p></body></html>"


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def create(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> httpx.Response:
    body: dict[str, Any] = {
        "title": "Senior Backend Engineer",
        "company": "Acme Payments",
        "description": BACKEND_JOB,
    }
    body.update(overrides)
    return await client.post(JOBS, headers=headers, json=body)


def use_web(app: FastAPI, web: FakeWeb) -> FakeWeb:
    app.state.portfolio_fetcher = web.fetcher()
    return web


# ------------------------------------------------------------------ create / read


async def test_create_saves_and_parses_the_job(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    response = await create(client, headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Senior Backend Engineer"
    assert body["company"] == "Acme Payments"
    assert body["status"] == "parsed"
    assert body["has_analysis"] is True
    assert body["source_url"] is None
    assert "Requirements" in body["description"]
    assert (await session.execute(select(func.count()).select_from(JobAnalysis))).scalar_one() == 1

    fetched = await client.get(f"{JOBS}/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_analysis_is_available_right_after_creation(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers)).json()["id"]
    response = await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["parser"] == "deterministic"
    assert body["provider"] is None
    parsed = body["result"]["parsed"]
    assert {"Python", "PostgreSQL", "Docker"} <= set(parsed["required_technical_skills"])
    assert {"AWS", "Terraform"} <= set(parsed["preferred_technical_skills"])
    assert "Python" in parsed["programming_languages"]
    assert parsed["seniority"] == {
        "level": "senior",
        "basis": "stated",
        "quote": parsed["seniority"]["quote"],
    }
    assert "Nothing here is verified" in body["result"]["notice"]


async def test_company_is_optional(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await create(client, headers, company=None)
    assert response.status_code == 201
    assert response.json()["company"] is None


async def test_list_is_newest_first_without_full_text(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    first = (await create(client, headers, title="First")).json()["id"]
    second = (await create(client, headers, title="Second", description=VAGUE_JOB)).json()["id"]
    listing = (await client.get(JOBS, headers=headers)).json()
    assert [j["id"] for j in listing] == [second, first]
    assert all("description" not in j for j in listing)


async def test_missing_job_is_404(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await client.get(f"{JOBS}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


async def test_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    for method, path in [
        ("GET", JOBS),
        ("POST", JOBS),
        ("GET", f"{JOBS}/00000000-0000-0000-0000-000000000000"),
        ("PUT", f"{JOBS}/00000000-0000-0000-0000-000000000000"),
        ("DELETE", f"{JOBS}/00000000-0000-0000-0000-000000000000"),
        ("GET", f"{JOBS}/00000000-0000-0000-0000-000000000000/analysis"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)


# ----------------------------------------------------------------- validation


async def test_description_or_url_is_required(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await client.post(JOBS, headers=headers, json={"title": "Engineer"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("description", ["", "   \n\t  "])
async def test_blank_description_without_url_is_rejected(
    client: httpx.AsyncClient, description: str
) -> None:
    headers = await headers_for(client)
    assert (await create(client, headers, description=description)).status_code == 422


async def test_too_short_description_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await create(client, headers, description="Python developer wanted")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_job_description"


async def test_too_long_description_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await create(client, headers, description="Python " * 6000)
    assert response.status_code == 422


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
async def test_title_is_required_and_bounded(client: httpx.AsyncClient, title: str) -> None:
    headers = await headers_for(client)
    assert (await create(client, headers, title=title)).status_code == 422


async def test_unknown_fields_are_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    assert (await create(client, headers, status="parsed")).status_code == 422
    assert (await create(client, headers, user_id="x")).status_code == 422


async def test_control_characters_are_removed_from_stored_text(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    text = BACKEND_JOB.replace("Requirements", "Require\x00ments\x07")
    response = await create(client, headers, description=text)
    assert response.status_code == 201
    assert "\x00" not in response.json()["description"]
    assert "\x07" not in response.json()["description"]


async def test_description_that_names_no_technologies_is_still_saved(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    text = "We are looking for a friendly office coordinator to welcome visitors every day."
    job_id = (await create(client, headers, description=text)).json()["id"]
    analysis = (await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)).json()
    parsed = analysis["result"]["parsed"]
    assert parsed["technical_skills"] == []
    assert any("No specific technologies" in w for w in parsed["warnings"])


# --------------------------------------------------------------------- update


async def test_update_description_reparses_the_job(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers)).json()["id"]
    response = await client.put(
        f"{JOBS}/{job_id}", headers=headers, json={"description": VAGUE_JOB}
    )
    assert response.status_code == 200, response.text
    assert response.json()["description"].startswith("Software Engineer")
    parsed = (await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)).json()["result"][
        "parsed"
    ]
    assert parsed["required_technical_skills"] == []
    assert "Django" in parsed["unspecified_importance_skills"]


async def test_update_company_only_keeps_the_analysis(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers)).json()["id"]
    before = (await session.execute(select(JobAnalysis))).scalar_one().id
    response = await client.put(f"{JOBS}/{job_id}", headers=headers, json={"company": "NewCo"})
    assert response.status_code == 200
    assert response.json()["company"] == "NewCo"
    session.expire_all()
    assert (await session.execute(select(JobAnalysis))).scalar_one().id == before


async def test_update_can_clear_company_and_link(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers, source_url="https://careers.example/jobs/1")).json()[
        "id"
    ]
    response = await client.put(
        f"{JOBS}/{job_id}", headers=headers, json={"company": None, "source_url": None}
    )
    assert response.status_code == 200
    assert response.json()["company"] is None
    assert response.json()["source_url"] is None


async def test_update_title_reparses_seniority(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    job_id = (
        await create(client, headers, title="Backend Engineer", description=VAGUE_JOB)
    ).json()["id"]
    response = await client.put(
        f"{JOBS}/{job_id}", headers=headers, json={"title": "Junior Backend Engineer"}
    )
    assert response.status_code == 200
    seniority = (await client.get(f"{JOBS}/{job_id}/analysis", headers=headers)).json()["result"][
        "parsed"
    ]["seniority"]
    assert seniority["level"] == "junior"


@pytest.mark.parametrize(
    "body",
    [{}, {"title": None}, {"description": None}, {"description": "  "}, {"description": "short"}],
)
async def test_invalid_updates_are_rejected(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers)).json()["id"]
    response = await client.put(f"{JOBS}/{job_id}", headers=headers, json=body)
    assert response.status_code == 422
    unchanged = (await client.get(f"{JOBS}/{job_id}", headers=headers)).json()
    assert unchanged["title"] == "Senior Backend Engineer"
    assert "Requirements" in unchanged["description"]


# --------------------------------------------------------------------- delete


async def test_delete_removes_job_and_analysis(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    job_id = (await create(client, headers)).json()["id"]
    assert (await client.delete(f"{JOBS}/{job_id}", headers=headers)).status_code == 204
    assert (await client.get(f"{JOBS}/{job_id}", headers=headers)).status_code == 404
    assert (await client.delete(f"{JOBS}/{job_id}", headers=headers)).status_code == 404
    for model in (JobDescription, JobAnalysis):
        assert (await session.execute(select(func.count()).select_from(model))).scalar_one() == 0


# ------------------------------------------------------------------ isolation


async def test_users_cannot_see_or_change_each_others_jobs(client: httpx.AsyncClient) -> None:
    ada = await headers_for(client, "ada@example.com")
    eve = await headers_for(client, "eve@example.com")
    job_id = (await create(client, ada)).json()["id"]

    assert (await client.get(JOBS, headers=eve)).json() == []
    for method, path, kwargs in [
        ("GET", f"{JOBS}/{job_id}", {}),
        ("GET", f"{JOBS}/{job_id}/analysis", {}),
        ("PUT", f"{JOBS}/{job_id}", {"json": {"title": "Hijacked"}}),
        ("DELETE", f"{JOBS}/{job_id}", {}),
    ]:
        response = await client.request(method, path, headers=eve, **kwargs)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "job_not_found"

    owner_view = (await client.get(f"{JOBS}/{job_id}", headers=ada)).json()
    assert owner_view["title"] == "Senior Backend Engineer"


# ---------------------------------------------------------------- URL import


async def test_job_text_can_be_read_from_a_public_url(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    web = use_web(app, FakeWeb(sites={"careers.example": {"/jobs/1": POSTING}}))
    headers = await headers_for(client)
    response = await client.post(
        JOBS,
        headers=headers,
        json={"title": "Backend Engineer", "source_url": "https://careers.example/jobs/1"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_url"] == "https://careers.example/jobs/1"
    assert "Strong proficiency in Python" in body["description"]
    assert [r.url.path for r in web.requests] == ["/jobs/1"]  # one page, nothing else
    analysis = (await client.get(f"{JOBS}/{body['id']}/analysis", headers=headers)).json()
    assert "Python" in analysis["result"]["parsed"]["required_technical_skills"]


async def test_pasted_text_wins_and_the_link_is_not_fetched(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    web = use_web(app, FakeWeb(sites={}))
    headers = await headers_for(client)
    response = await create(client, headers, source_url="https://careers.example/jobs/1")
    assert response.status_code == 201
    assert response.json()["source_url"] == "https://careers.example/jobs/1"
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/job",
        "http://127.0.0.1/job",
        "http://169.254.169.254/latest/meta-data/",
        "http://2130706433/job",
        "https://user:pw@careers.example/job",
        "file:///etc/passwd",
        "ftp://careers.example/job",
        "https://careers.example:8443/job",
    ],
)
async def test_unsafe_job_urls_are_rejected_without_a_request(
    client: httpx.AsyncClient, app: FastAPI, url: str
) -> None:
    web = use_web(app, FakeWeb())
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": url}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "job_url_rejected"
    assert web.requests == []
    assert web.lookups == []


async def test_a_host_that_resolves_to_a_private_address_is_rejected(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    web = use_web(app, FakeWeb(dns={"evil.example": ["93.184.216.34", "10.0.0.5"]}))
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": "https://evil.example/job"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "job_url_rejected"
    assert web.requests == []
    assert "10.0.0.5" not in response.text


async def test_redirect_to_an_internal_address_is_rejected(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    web = use_web(app, FakeWeb(handler=handler))
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": "https://careers.example/j"}
    )
    assert response.status_code == 422
    assert len(web.requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/123",
        "https://uk.indeed.com/viewjob?jk=abc",
        "https://www.glassdoor.com/job-listing/x",
    ],
)
async def test_restricted_platforms_are_never_fetched(
    client: httpx.AsyncClient, app: FastAPI, url: str
) -> None:
    web = use_web(app, FakeWeb())
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": url}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "job_platform_not_supported"
    assert "paste" in response.json()["error"]["message"].lower()
    assert web.requests == [] and web.lookups == []


async def test_restricted_platform_link_is_fine_as_a_reference_next_to_pasted_text(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    web = use_web(app, FakeWeb())
    headers = await headers_for(client)
    response = await create(client, headers, source_url="https://www.linkedin.com/jobs/view/123")
    assert response.status_code == 201
    assert web.requests == []


async def test_redirect_onto_a_restricted_platform_is_refused(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "careers.example":
            return httpx.Response(301, headers={"location": "https://www.linkedin.com/jobs/1"})
        return httpx.Response(200, content=POSTING.encode(), headers={"content-type": "text/html"})

    use_web(app, FakeWeb(handler=handler))
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": "https://careers.example/j"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "job_platform_not_supported"


async def test_page_without_readable_text_asks_for_pasting(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    empty = "<html><body><div id='root'></div><script>render()</script></body></html>"
    use_web(app, FakeWeb(sites={"spa.example": {"/job": empty}}))
    headers = await headers_for(client)
    response = await client.post(
        JOBS, headers=headers, json={"title": "Engineer", "source_url": "https://spa.example/job"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "job_text_not_found"


async def test_fetch_failures_are_reported_as_bad_gateway(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    use_web(app, FakeWeb(sites={"careers.example": {}}))
    headers = await headers_for(client)
    response = await client.post(
        JOBS,
        headers=headers,
        json={"title": "Engineer", "source_url": "https://careers.example/gone"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "portfolio_http_error"
    assert (await client.get(JOBS, headers=headers)).json() == []  # nothing was saved


async def test_update_with_a_new_link_reads_the_new_text(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    use_web(app, FakeWeb(sites={"careers.example": {"/jobs/2": POSTING}}))
    headers = await headers_for(client)
    job_id = (await create(client, headers, description=VAGUE_JOB)).json()["id"]
    response = await client.put(
        f"{JOBS}/{job_id}", headers=headers, json={"source_url": "https://careers.example/jobs/2"}
    )
    assert response.status_code == 200, response.text
    assert "Strong proficiency in Python" in response.json()["description"]


# ----------------------------------------------------------- status & privacy


async def test_parser_failure_marks_the_job_failed_without_logging_its_text(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(title: str, description: str) -> None:
        raise RuntimeError(description)

    monkeypatch.setattr("app.services.jobs.parse_job", boom)
    headers = await headers_for(client)
    caplog.set_level(logging.DEBUG)
    response = await create(client, headers)
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["has_analysis"] is False
    assert (
        await client.get(f"{JOBS}/{response.json()['id']}/analysis", headers=headers)
    ).status_code == 404
    assert "Strong proficiency in Python" not in caplog.text
    assert "Acme Payments" not in caplog.text


async def test_job_text_is_never_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    headers = await headers_for(client)
    await create(client, headers)
    assert "Strong proficiency in Python" not in caplog.text
