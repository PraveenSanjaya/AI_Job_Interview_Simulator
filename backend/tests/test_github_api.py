import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import GitHubRateLimitedError, GitHubUnavailableError
from app.models import IntegrationSource
from tests.fakes_github import FakeGitHubClient, api_repo, api_user
from tests.helpers import bearer, register_and_login

pytestmark = pytest.mark.anyio

GITHUB = "/api/v1/integrations/github"


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def connect(
    client: httpx.AsyncClient, headers: dict[str, str], username: str = "janedoe"
) -> httpx.Response:
    return await client.post(GITHUB, headers=headers, json={"username": username})


async def test_connect_returns_observed_facts_and_stores_them(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    response = await connect(client, headers, "https://github.com/janedoe")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_ref"] == "janedoe"
    snap = body["snapshot"]
    assert snap["login"] == "janedoe"
    assert snap["repositories"][0]["name"] == "interview-sim"
    assert snap["language_distribution"] == {"Python": 2, "Shell": 1}
    assert "AI" not in body  # no assessment at this stage
    stored = (await session.execute(select(IntegrationSource))).scalar_one()
    assert stored.kind.value == "github" and stored.source_ref == "janedoe"

    assert (await client.get(GITHUB, headers=headers)).json() == body


async def test_connect_does_not_touch_the_candidate_profile(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    before = (await client.get("/api/v1/profile", headers=headers)).json()
    await connect(client, headers)
    after = (await client.get("/api/v1/profile", headers=headers)).json()
    assert before == after  # source data stays separate from confirmed profile data
    assert after["skills"] == [] and after["projects"] == []


@pytest.mark.parametrize(
    "username", ["", "not a user", "../etc", "https://evil.example/janedoe", "-bad", "a" * 100]
)
async def test_invalid_usernames_are_rejected_without_calling_github(
    app: FastAPI, client: httpx.AsyncClient, username: str
) -> None:
    fake = FakeGitHubClient()
    app.state.github_client = fake
    headers = await headers_for(client)
    response = await connect(client, headers, username)
    assert response.status_code == 422
    assert fake.calls == []


async def test_unknown_field_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await client.post(GITHUB, headers=headers, json={"username": "janedoe", "x": 1})
    assert response.status_code == 422


async def test_missing_nonexistent_or_private_profile_is_a_clean_404(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    app.state.github_client = FakeGitHubClient(user={})
    headers = await headers_for(client)
    response = await connect(client, headers, "ghost")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "github_user_not_found"
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 0


async def test_organizations_are_rejected(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.github_client = FakeGitHubClient(user=api_user(type="Organization"))
    headers = await headers_for(client)
    response = await connect(client, headers, "acme")
    assert response.status_code == 422 and response.json()["error"]["code"] == "github_not_a_user"


async def test_github_rate_limit_and_outage_are_reported_with_proper_statuses(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    app.state.github_client = FakeGitHubClient(error=GitHubRateLimitedError(90))
    limited = await connect(client, headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "github_rate_limited"
    assert limited.headers["retry-after"] == "90"

    app.state.github_client = FakeGitHubClient(error=GitHubUnavailableError("down"))
    down = await connect(client, headers)
    assert down.status_code == 502 and down.json()["error"]["code"] == "github_unavailable"


async def test_failed_refresh_keeps_the_existing_connection(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    await connect(client, headers)
    app.state.github_client = FakeGitHubClient(error=GitHubUnavailableError("down"))
    assert (await connect(client, headers, "someone-else")).status_code == 502
    assert (await client.get(GITHUB, headers=headers)).json()["source_ref"] == "janedoe"


async def test_reconnecting_replaces_the_source(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    await connect(client, headers)
    app.state.github_client = FakeGitHubClient(
        user=api_user(login="other", public_repos=1), repos=[api_repo("solo")], readmes={}
    )
    response = await connect(client, headers, "other")
    assert response.json()["snapshot"]["login"] == "other"
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 1


async def test_empty_and_large_profiles_are_both_handled(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    app.state.github_client = FakeGitHubClient(user=api_user(public_repos=0), repos=[])
    empty = await connect(client, headers)
    assert empty.status_code == 200 and empty.json()["snapshot"]["repositories"] == []

    many = [api_repo(f"r{i}", language="Python") for i in range(100)]
    app.state.github_client = FakeGitHubClient(user=api_user(public_repos=900), repos=many)
    large = await connect(client, headers)
    snap = large.json()["snapshot"]
    assert snap["repos_listed"] == 100 and snap["repos_truncated"] is True


async def test_get_and_delete_when_not_connected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    assert (await client.get(GITHUB, headers=headers)).status_code == 404
    response = await client.delete(GITHUB, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "source_not_connected"


async def test_delete_removes_the_stored_snapshot(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    await connect(client, headers)
    assert (await client.delete(GITHUB, headers=headers)).status_code == 204
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 0
    assert (await client.get(GITHUB, headers=headers)).status_code == 404


async def test_authentication_is_required(client: httpx.AsyncClient) -> None:
    assert (await client.post(GITHUB, json={"username": "janedoe"})).status_code == 401
    assert (await client.get(GITHUB)).status_code == 401
    assert (await client.delete(GITHUB)).status_code == 401


async def test_users_only_see_and_remove_their_own_connection(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    await connect(client, ada)

    assert (await client.get(GITHUB, headers=bob)).status_code == 404
    assert (await client.delete(GITHUB, headers=bob)).status_code == 404
    assert (await client.get(GITHUB, headers=ada)).status_code == 200  # untouched

    app.state.github_client = FakeGitHubClient(user=api_user(login="bobhub"), repos=[])
    await connect(client, bob, "bobhub")
    assert (await client.get(GITHUB, headers=ada)).json()["source_ref"] == "janedoe"
    assert (await client.get(GITHUB, headers=bob)).json()["source_ref"] == "bobhub"


async def test_connecting_is_rate_limited_per_user(app: FastAPI, client: httpx.AsyncClient) -> None:
    from app.core.rate_limit import InMemoryRateLimiter

    headers = await headers_for(client)
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    codes = [(await connect(client, headers)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
