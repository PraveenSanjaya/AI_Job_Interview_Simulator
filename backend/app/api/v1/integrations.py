"""Public-source integrations: GitHub profile, portfolio site, and their analysis."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.ai.base import LLMProvider
from app.ai.integration_schemas import IntegrationAnalysisResult
from app.ai.suggestions import build_integration_suggestion
from app.api.deps import (
    CurrentUserDep,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
    get_llm_provider,
)
from app.integrations.github.client import GitHubClient
from app.integrations.portfolio.crawler import PageFetcher
from app.models import IntegrationAnalysis, IntegrationSource
from app.models.enums import IntegrationKind
from app.schemas.integrations import (
    AnalysisRequest,
    AnalysisSummary,
    GitHubConnectRequest,
    GitHubSourceResponse,
    IntegrationAnalysisResponse,
    PortfolioConnectRequest,
    PortfolioSourceResponse,
)
from app.schemas.profile import ApplyResult, ApplyToProfileRequest
from app.services.integration_analysis import IntegrationAnalysisRunner
from app.services.integrations import IntegrationService
from app.services.profile import ProfileService

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


def get_analysis_runner(
    session: SessionDep,
    settings: SettingsDep,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> IntegrationAnalysisRunner:
    return IntegrationAnalysisRunner(session, provider, settings.ai_max_input_chars)


AnalysisRunnerDep = Annotated[IntegrationAnalysisRunner, Depends(get_analysis_runner)]


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
    await limiter.hit(f"integration:user:{user.id}")
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
    await limiter.hit(f"integration:user:{user.id}")
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


# --------------------------------------------------------------------- analysis


def _analysis_response(analysis: IntegrationAnalysis) -> IntegrationAnalysisResponse:
    result = IntegrationAnalysisResult.model_validate(analysis.result)
    suggestion, notes = build_integration_suggestion(result)
    return IntegrationAnalysisResponse(
        id=analysis.id,
        created_at=analysis.created_at,
        provider=analysis.provider,
        model=analysis.model,
        consent_external_ai=analysis.consent_external_ai,
        input_truncated=analysis.input_truncated,
        github_source_id=analysis.github_source_id,
        portfolio_source_id=analysis.portfolio_source_id,
        resume_id=analysis.resume_id,
        result=result,
        profile_suggestion=suggestion,
        suggestion_notes=notes,
    )


@router.post(
    "/analysis", response_model=IntegrationAnalysisResponse, status_code=status.HTTP_201_CREATED
)
async def create_analysis(
    body: AnalysisRequest,
    user: CurrentUserDep,
    runner: AnalysisRunnerDep,
    limiter: RateLimiterDep,
) -> IntegrationAnalysisResponse:
    """Analyse your connected GitHub/portfolio (and optionally an analysed resume).

    * 503 ``ai_unavailable``: no AI provider is configured.
    * 409 ``no_sources_connected`` / 404 ``source_not_connected``: nothing to analyse.
    * 403 ``ai_consent_required``: the provider is external and ``allow_external_ai``
      was not true. Nothing is sent.
    * 502/504/429: invalid AI output, provider timeout, provider rate limit.

    ``result.facts`` are computed from the stored sources. ``result.assessment`` is AI
    opinion; claims that the sources do not support were removed
    (``unverified_items_removed``). Neither is a measure of ability.
    """
    await limiter.hit(f"integration-analysis:user:{user.id}")
    analysis = await runner.run(
        user,
        include=body.include,
        resume_id=body.resume_id,
        allow_external_ai=body.allow_external_ai,
    )
    return _analysis_response(analysis)


@router.get("/analysis", response_model=list[AnalysisSummary])
async def list_analyses(user: CurrentUserDep, runner: AnalysisRunnerDep) -> list[AnalysisSummary]:
    items = await runner.list_all(user)
    return [
        AnalysisSummary(
            id=a.id,
            created_at=a.created_at,
            provider=a.provider,
            model=a.model,
            sources_used=list(a.result.get("facts", {}).get("sources_used", [])),
        )
        for a in items
    ]


@router.get("/analysis/{analysis_id}", response_model=IntegrationAnalysisResponse)
async def get_analysis(
    analysis_id: uuid.UUID, user: CurrentUserDep, runner: AnalysisRunnerDep
) -> IntegrationAnalysisResponse:
    return _analysis_response(await runner.get(user, analysis_id))


@router.delete("/analysis/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: uuid.UUID, user: CurrentUserDep, runner: AnalysisRunnerDep
) -> None:
    await runner.delete(user, analysis_id)


@router.post("/analysis/{analysis_id}/apply-to-profile", response_model=ApplyResult)
async def apply_analysis_to_profile(
    analysis_id: uuid.UUID,
    body: ApplyToProfileRequest,
    user: CurrentUserDep,
    runner: AnalysisRunnerDep,
) -> ApplyResult:
    """Apply only what you send (typically the reviewed ``profile_suggestion``).

    Nothing is applied automatically. Existing profile data is preserved: lists are merged
    without duplicates (``mode="replace"`` is an explicit per-section choice) and a
    scalar that already differs is kept unless ``overwrite_existing`` is true.
    """
    profile, applied, skipped = await runner.apply_to_profile(user, analysis_id, body)
    return ApplyResult(
        applied=applied, skipped=skipped, profile=ProfileService.to_response(user, profile)
    )
