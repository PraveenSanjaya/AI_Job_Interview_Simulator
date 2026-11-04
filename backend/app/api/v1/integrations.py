"""Public-source integrations: GitHub profile, portfolio site, and their analysis."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep, SettingsDep
from app.integrations.github.client import GitHubClient
from app.integrations.portfolio.crawler import PageFetcher
from app.models import IntegrationSource
from app.models.enums import IntegrationKind
from app.schemas.integrations import (
    GitHubConnectRequest,
    GitHubSourceResponse,
    PortfolioConnectRequest,
    PortfolioSourceResponse,
)
from app.services.integrations import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


def get_github_client(request: Request) -> GitHubClient:
    client: GitHubClient = request.app.state.github_client
    return client


def get_page_fetcher(request: Request) -> PageFetcher:
    fetcher: PageFetcher = request.app.state.portfolio_fetcher
    return fetcher


def get_integration_service(
    session: SessionDep,
    settings: SettingsDep,
    github: Annotated[GitHubClient, Depends(get_github_client)],
    pages: Annotated[PageFetcher, Depends(get_page_fetcher)],
) -> IntegrationService:
    return IntegrationService(session, settings, github, pages)


IntegrationServiceDep = Annotated[IntegrationService, Depends(get_integration_service)]


def _github_response(
    service: IntegrationService, source: IntegrationSource
) -> GitHubSourceResponse:
    return GitHubSourceResponse(
        source_ref=source.source_ref,
        fetched_at=source.fetched_at,
        snapshot=service.github_snapshot(source),
    )


@router.post("/github", response_model=GitHubSourceResponse)
async def connect_github(
    body: GitHubConnectRequest,
    user: CurrentUserDep,
    service: IntegrationServiceDep,
    limiter: RateLimiterDep,
) -> GitHubSourceResponse:
    """Connect (or refresh/replace) your public GitHub profile.

    Only public data is read through GitHub's official API; no GitHub login or
    permissions are involved. Replacing the connection also deletes analyses that were
    derived from the previous one. Errors: 422 invalid username, 404 user not found,
    429 GitHub rate limit, 502 GitHub unavailable.
    """
    limiter.hit(f"integration:user:{user.id}")
    source = await service.connect_github(user, body.username)
    return _github_response(service, source)


@router.get("/github", response_model=GitHubSourceResponse)
async def get_github(user: CurrentUserDep, service: IntegrationServiceDep) -> GitHubSourceResponse:
    return _github_response(service, await service.get_source(user, IntegrationKind.GITHUB))


@router.delete("/github", status_code=status.HTTP_204_NO_CONTENT)
async def delete_github(user: CurrentUserDep, service: IntegrationServiceDep) -> None:
    """Disconnect GitHub and delete the stored snapshot and analyses derived from it."""
    await service.remove_source(user, IntegrationKind.GITHUB)


@router.post("/portfolio", response_model=PortfolioSourceResponse)
async def connect_portfolio(
    body: PortfolioConnectRequest,
    user: CurrentUserDep,
    service: IntegrationServiceDep,
    limiter: RateLimiterDep,
) -> PortfolioSourceResponse:
    """Connect (or refresh/replace) your public portfolio site.

    The server fetches the page you give (plus a few same-site pages) with strict
    safeguards: only public http(s) addresses on ports 80/443; private, loopback,
    link-local and reserved networks are refused; DNS answers and every redirect are
    validated; timeouts and size limits apply; no JavaScript is run. Errors:
    422 ``portfolio_url_rejected``, 502 ``portfolio_fetch_failed`` (and specific codes
    such as ``portfolio_timeout``).
    """
    limiter.hit(f"integration:user:{user.id}")
    source = await service.connect_portfolio(user, body.url)
    return _portfolio_response(service, source)


@router.get("/portfolio", response_model=PortfolioSourceResponse)
async def get_portfolio(
    user: CurrentUserDep, service: IntegrationServiceDep
) -> PortfolioSourceResponse:
    return _portfolio_response(service, await service.get_source(user, IntegrationKind.PORTFOLIO))


@router.delete("/portfolio", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(user: CurrentUserDep, service: IntegrationServiceDep) -> None:
    """Disconnect the portfolio and delete the stored pages and analyses derived from them."""
    await service.remove_source(user, IntegrationKind.PORTFOLIO)


def _portfolio_response(
    service: IntegrationService, source: IntegrationSource
) -> PortfolioSourceResponse:
    return PortfolioSourceResponse(
        source_ref=source.source_ref,
        fetched_at=source.fetched_at,
        snapshot=service.portfolio_snapshot(source),
    )
