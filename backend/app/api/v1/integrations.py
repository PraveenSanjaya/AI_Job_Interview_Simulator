"""Public-source integrations: GitHub profile, portfolio site, and their analysis."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep, SettingsDep
from app.integrations.github.client import GitHubClient
from app.models import IntegrationSource
from app.models.enums import IntegrationKind
from app.schemas.integrations import GitHubConnectRequest, GitHubSourceResponse
from app.services.integrations import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


def get_github_client(request: Request) -> GitHubClient:
    client: GitHubClient = request.app.state.github_client
    return client


def get_integration_service(
    session: SessionDep,
    settings: SettingsDep,
    github: Annotated[GitHubClient, Depends(get_github_client)],
) -> IntegrationService:
    return IntegrationService(session, settings, github)


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
