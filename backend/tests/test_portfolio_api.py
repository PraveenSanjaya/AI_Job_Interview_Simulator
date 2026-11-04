import gzip

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IntegrationSource
from tests.fakes_portfolio import PUBLIC, FakeWeb
from tests.helpers import bearer, register_and_login

pytestmark = pytest.mark.anyio

PORTFOLIO = "/api/v1/integrations/portfolio"


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def connect(
    client: httpx.AsyncClient, headers: dict[str, str], url: str = "https://jane.example/"
) -> httpx.Response:
    return await client.post(PORTFOLIO, headers=headers, json={"url": url})


async def test_connect_returns_pages_with_source_urls(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    response = await connect(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_ref"] == "https://jane.example/"
    pages = body["snapshot"]["pages"]
    assert [p["url"] for p in pages] == ["https://jane.example/", "https://jane.example/projects"]
    assert pages[0]["title"] == "Jane Doe - Portfolio"
    assert "FastAPI, React and PostgreSQL" in pages[1]["text_excerpt"]
    assert any(link["url"] == "https://github.com/janedoe" for link in pages[0]["external_links"])
    assert "not verified experience" in body["snapshot"]["notice"]
    stored = (await session.execute(select(IntegrationSource))).scalar_one()
    assert stored.kind.value == "portfolio"
    assert (await client.get(PORTFOLIO, headers=headers)).json() == body


async def test_connect_does_not_touch_the_candidate_profile(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    before = (await client.get("/api/v1/profile", headers=headers)).json()
    await connect(client, headers)
    assert (await client.get("/api/v1/profile", headers=headers)).json() == before


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://2130706433/",
        "http://0x7f.0.0.1/",
        "file:///etc/passwd",
        "ftp://jane.example/",
        "gopher://jane.example/",
        "javascript:alert(1)",
        "https://user:pw@jane.example/",
        "https://jane.example:8443/",
        "http://metadata.google.internal/",
        "not a url",
        "",
    ],
)
async def test_internal_and_malformed_urls_are_rejected_without_any_request(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, url: str
) -> None:
    web = FakeWeb()
    app.state.portfolio_fetcher = web.fetcher()
    headers = await headers_for(client)
    response = await connect(client, headers, url)
    assert response.status_code == 422, (url, response.text)
    assert response.json()["error"]["code"] in {"portfolio_url_rejected", "validation_error"}
    assert web.requests == [] and web.lookups == []
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 0


async def test_hostname_resolving_to_a_private_address_is_rejected(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    web = FakeWeb(dns={"evil.example": ["10.1.1.1"], "mixed.example": [PUBLIC, "127.0.0.1"]})
    app.state.portfolio_fetcher = web.fetcher()
    headers = await headers_for(client)
    for host in ("evil.example", "mixed.example"):
        response = await connect(client, headers, f"https://{host}/")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "portfolio_url_rejected"
    assert web.requests == []


async def test_redirect_into_the_internal_network_is_blocked(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    web = FakeWeb(
        handler=lambda r: httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )
    )
    app.state.portfolio_fetcher = web.fetcher()
    headers = await headers_for(client)
    response = await connect(client, headers)
    assert response.status_code == 422
    assert len(web.requests) == 1


async def test_unreachable_missing_and_slow_sites_return_clean_502s(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    cases = [
        (FakeWeb(sites={}), "portfolio_http_error"),  # 404
        (FakeWeb(handler=timeout), "portfolio_timeout"),
        (FakeWeb(handler=lambda r: httpx.Response(500)), "portfolio_http_error"),
        (FakeWeb(dns={"jane.example": []}), "portfolio_unreachable"),
    ]
    for web, code in cases:
        app.state.portfolio_fetcher = web.fetcher()
        response = await connect(client, headers)
        assert response.status_code == 502, code
        assert response.json()["error"]["code"] == code


async def test_non_html_and_oversized_pages_are_rejected(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    pdf = FakeWeb(
        handler=lambda r: httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    app.state.portfolio_fetcher = pdf.fetcher()
    response = await connect(client, headers)
    assert response.json()["error"]["code"] == "portfolio_unsupported_content_type"

    bomb = gzip.compress(b"A" * 3_000_000)
    big = FakeWeb(
        handler=lambda r: httpx.Response(
            200, content=bomb, headers={"content-type": "text/html", "content-encoding": "gzip"}
        )
    )
    app.state.portfolio_fetcher = big.fetcher(max_bytes=100_000)
    assert (await connect(client, headers)).json()["error"]["code"] == "portfolio_too_large"


async def test_failed_refresh_keeps_the_existing_connection(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers = await headers_for(client)
    await connect(client, headers)
    app.state.portfolio_fetcher = FakeWeb(sites={}).fetcher()
    assert (await connect(client, headers, "https://other.example/")).status_code == 502
    assert (await client.get(PORTFOLIO, headers=headers)).json()["source_ref"] == (
        "https://jane.example/"
    )


async def test_reconnecting_replaces_and_url_can_be_updated(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    await connect(client, headers)
    web = FakeWeb(sites={"new.example": {"/": "<title>New</title><p>hi there</p>"}})
    app.state.portfolio_fetcher = web.fetcher()
    response = await connect(client, headers, "https://new.example/")
    assert response.json()["source_ref"] == "https://new.example/"
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 1


async def test_get_and_delete(client: httpx.AsyncClient, session: AsyncSession) -> None:
    headers = await headers_for(client)
    assert (await client.get(PORTFOLIO, headers=headers)).status_code == 404
    assert (await client.delete(PORTFOLIO, headers=headers)).status_code == 404
    await connect(client, headers)
    assert (await client.delete(PORTFOLIO, headers=headers)).status_code == 204
    assert (await client.get(PORTFOLIO, headers=headers)).status_code == 404
    assert (
        await session.execute(select(func.count()).select_from(IntegrationSource))
    ).scalar() == 0


async def test_authentication_is_required(client: httpx.AsyncClient) -> None:
    assert (await client.post(PORTFOLIO, json={"url": "https://jane.example/"})).status_code == 401
    assert (await client.get(PORTFOLIO)).status_code == 401
    assert (await client.delete(PORTFOLIO)).status_code == 401


async def test_users_are_isolated_and_github_and_portfolio_are_independent(
    client: httpx.AsyncClient,
) -> None:
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    await connect(client, ada)
    assert (await client.get(PORTFOLIO, headers=bob)).status_code == 404
    assert (await client.delete(PORTFOLIO, headers=bob)).status_code == 404

    await client.post("/api/v1/integrations/github", headers=ada, json={"username": "janedoe"})
    assert (await client.delete("/api/v1/integrations/github", headers=ada)).status_code == 204
    assert (await client.get(PORTFOLIO, headers=ada)).status_code == 200  # unaffected


async def test_unknown_fields_are_rejected_and_requests_are_rate_limited(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from app.core.rate_limit import InMemoryRateLimiter

    headers = await headers_for(client)
    bad = await client.post(PORTFOLIO, headers=headers, json={"url": "https://a.example/", "x": 1})
    assert bad.status_code == 422
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    codes = [(await connect(client, headers)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
