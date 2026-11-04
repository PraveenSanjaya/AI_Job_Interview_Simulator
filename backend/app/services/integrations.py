"""Connecting, refreshing and removing public sources (GitHub, portfolio).

A source row holds only what the public source said (observed facts). It is kept apart
from the candidate's own profile, which is never modified here.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.errors import SourceNotConnectedError
from app.integrations.github.client import GitHubClient
from app.integrations.github.snapshot import GitHubSnapshot, build_github_snapshot
from app.integrations.github.username import parse_github_username
from app.integrations.portfolio.crawler import PageFetcher, PortfolioSnapshot, collect_portfolio
from app.integrations.portfolio.safe_fetch import parse_public_url
from app.models import IntegrationSource, User
from app.models.enums import IntegrationKind
from app.repositories.integrations import IntegrationRepository


class IntegrationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        github: GitHubClient,
        pages: PageFetcher,
    ) -> None:
        self._session = session
        self._settings = settings
        self._github = github
        self._pages = pages
        self._repo = IntegrationRepository(session)

    # ------------------------------------------------------------------ GitHub

    async def connect_github(self, user: User, username_or_url: str) -> IntegrationSource:
        """Fetch the public profile first; only then replace the existing connection, so a
        failed refresh never destroys a working one."""
        login = parse_github_username(username_or_url)
        snapshot = await build_github_snapshot(
            self._github,
            login,
            max_repos=self._settings.github_max_repos,
            readme_repos=self._settings.github_readme_repos,
        )
        source = await self._repo.replace_source(
            user.id, IntegrationKind.GITHUB, snapshot.login, snapshot.model_dump(mode="json")
        )
        source.fetched_at = datetime.now(UTC)
        await self._session.commit()
        return source

    # ------------------------------------------------------------------ portfolio

    async def connect_portfolio(self, user: User, url: str) -> IntegrationSource:
        """Validate the address, fetch the public pages (SSRF-safe), then replace the
        existing connection. Nothing is stored if validation or the first fetch fails."""
        normalised = parse_public_url(url)  # rejects non-public targets before any request
        requested = f"{normalised.scheme}://{normalised.host}{normalised.path_and_query}"
        snapshot = await collect_portfolio(
            self._pages, requested, max_pages=self._settings.portfolio_max_pages
        )
        source = await self._repo.replace_source(
            user.id,
            IntegrationKind.PORTFOLIO,
            snapshot.pages[0].url,
            snapshot.model_dump(mode="json"),
        )
        await self._session.commit()
        return source

    @staticmethod
    def portfolio_snapshot(source: IntegrationSource) -> PortfolioSnapshot:
        return PortfolioSnapshot.model_validate(source.snapshot)

    # ------------------------------------------------------------------ shared

    async def get_source(self, user: User, kind: IntegrationKind) -> IntegrationSource:
        source = await self._repo.get_source(user.id, kind)
        if source is None:
            raise SourceNotConnectedError(f"No {kind.value} source is connected")
        return source

    async def remove_source(self, user: User, kind: IntegrationKind) -> None:
        """Delete the connection and everything derived from it."""
        if not await self._repo.delete_source(user.id, kind):
            raise SourceNotConnectedError(f"No {kind.value} source is connected")
        await self._session.commit()

    @staticmethod
    def github_snapshot(source: IntegrationSource) -> GitHubSnapshot:
        return GitHubSnapshot.model_validate(source.snapshot)
