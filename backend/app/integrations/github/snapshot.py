"""Build a snapshot of *observed facts* from a public GitHub profile.

Everything here comes straight from GitHub's API or is simple arithmetic over it. There
is no AI involvement and nothing is inferred: language "distribution" is the number of
the user's own (non-fork) repositories per primary language label, "activity" is the
count of repositories with a recent push, and star totals are summed star counts.
Contribution graphs and commit counts are not available from the REST API and are
therefore not reported.

All text (bio, descriptions, READMEs) is untrusted third-party content.
"""

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.errors import GitHubNotAUserError, GitHubRateLimitedError
from app.integrations.github.client import GitHubClient
from app.integrations.github.username import is_valid_repo_name

README_MAX_BYTES = 40_000
README_EXCERPT_CHARS = 3000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value).strip()
    return text[:limit] or None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _github_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://github.com/") else None


def _http_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


class RepositoryFact(BaseModel):
    name: str
    url: str
    description: str | None = None
    homepage: str | None = None
    primary_language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    is_fork: bool = False
    is_archived: bool = False
    created_at: datetime | None = None
    pushed_at: datetime | None = None
    readme_excerpt: str | None = None
    readme_truncated: bool = False


class ActivityFacts(BaseModel):
    """Counts of the user's own repositories by last push (not commit counts)."""

    own_repos_pushed_last_90_days: int
    own_repos_pushed_last_365_days: int
    most_recent_push: datetime | None = None


class GitHubSnapshot(BaseModel):
    login: str
    profile_url: str
    name: str | None = None
    bio: str | None = None
    location: str | None = None
    blog: str | None = None
    account_created_at: datetime | None = None
    followers: int = 0
    public_repos_total: int = 0
    repos_listed: int = 0
    repos_truncated: bool = False
    repositories: list[RepositoryFact] = Field(default_factory=list)
    language_distribution: dict[str, int] = Field(default_factory=dict)
    total_stars_own_repos: int = 0
    activity: ActivityFacts
    readmes_fetched: int = 0
    readme_fetch_incomplete: bool = False
    fetched_at: datetime
    notice: str = (
        "Observed from GitHub's public API at fetched_at. Counts describe public repositories "
        "only and are not a measure of programming ability."
    )


def _repo_from_api(item: dict[str, Any]) -> RepositoryFact | None:
    name = item.get("name")
    url = _github_url(item.get("html_url"))
    if not isinstance(name, str) or not is_valid_repo_name(name) or url is None:
        return None
    topics = item.get("topics")
    return RepositoryFact(
        name=name,
        url=url,
        description=_clean(item.get("description"), 500),
        homepage=_http_url(item.get("homepage")),
        primary_language=_clean(item.get("language"), 50),
        topics=[t for t in (topics if isinstance(topics, list) else []) if isinstance(t, str)][:20],
        stars=int(item.get("stargazers_count") or 0),
        forks=int(item.get("forks_count") or 0),
        is_fork=bool(item.get("fork")),
        is_archived=bool(item.get("archived")),
        created_at=_parse_dt(item.get("created_at")),
        pushed_at=_parse_dt(item.get("pushed_at")),
    )


def _notable_order(repo: RepositoryFact) -> tuple[int, float]:
    pushed = repo.pushed_at.timestamp() if repo.pushed_at else 0.0
    return (repo.stars, pushed)


async def build_github_snapshot(
    client: GitHubClient,
    login: str,
    *,
    max_repos: int,
    readme_repos: int,
    now: datetime | None = None,
) -> GitHubSnapshot:
    now = now or datetime.now(UTC)
    user = await client.get_user(login)
    if user.get("type") != "User":
        raise GitHubNotAUserError("That GitHub account is an organization, not a person")

    canonical = _clean(user.get("login"), 39) or login
    raw_repos = await client.list_public_repos(canonical, max_repos)
    repos = [r for r in (_repo_from_api(item) for item in raw_repos) if r is not None]

    own = [r for r in repos if not r.is_fork]
    languages = Counter(r.primary_language for r in own if r.primary_language)

    # READMEs only for the most notable of the user's own repositories (bounded API use).
    candidates = sorted((r for r in own if not r.is_archived), key=_notable_order, reverse=True)
    fetched = 0
    incomplete = False
    if readme_repos > 0:
        semaphore = asyncio.Semaphore(3)

        async def load(repo: RepositoryFact) -> None:
            nonlocal fetched, incomplete
            async with semaphore:
                if incomplete:
                    return
                try:
                    text = await client.get_readme(canonical, repo.name, README_MAX_BYTES)
                except GitHubRateLimitedError:
                    incomplete = True  # keep what we have instead of failing the whole analysis
                    return
                except Exception:
                    incomplete = True
                    return
            if text:
                cleaned = _CONTROL.sub("", text).strip()
                repo.readme_excerpt = cleaned[:README_EXCERPT_CHARS] or None
                repo.readme_truncated = len(cleaned) > README_EXCERPT_CHARS
                fetched += 1

        await asyncio.gather(*(load(r) for r in candidates[:readme_repos]))

    pushes = [r.pushed_at for r in own if r.pushed_at]
    activity = ActivityFacts(
        own_repos_pushed_last_90_days=sum(1 for p in pushes if p >= now - timedelta(days=90)),
        own_repos_pushed_last_365_days=sum(1 for p in pushes if p >= now - timedelta(days=365)),
        most_recent_push=max(pushes) if pushes else None,
    )
    total = int(user.get("public_repos") or 0)
    return GitHubSnapshot(
        login=canonical,
        profile_url=f"https://github.com/{canonical}",
        name=_clean(user.get("name"), 100),
        bio=_clean(user.get("bio"), 500),
        location=_clean(user.get("location"), 100),
        blog=_http_url(user.get("blog")),
        account_created_at=_parse_dt(user.get("created_at")),
        followers=int(user.get("followers") or 0),
        public_repos_total=total,
        repos_listed=len(repos),
        repos_truncated=total > len(raw_repos),
        repositories=repos,
        language_distribution=dict(languages.most_common()),
        total_stars_own_repos=sum(r.stars for r in own),
        activity=activity,
        readmes_fetched=fetched,
        readme_fetch_incomplete=incomplete,
        fetched_at=now,
    )
