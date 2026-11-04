"""Bounded, same-host retrieval of a candidate's portfolio pages.

Not a general crawler: it fetches the page the candidate supplied plus at most a few
more pages **on the same host**, chosen by simple relevance keywords, honouring
``robots.txt`` for those extra pages. Every request goes through the SSRF-safe fetcher.
"""

from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pydantic import BaseModel, Field

from app.integrations.errors import (
    PortfolioFetchError,
    PortfolioHttpError,
    PortfolioUrlRejectedError,
)
from app.integrations.portfolio.extract import ParsedPage, extract_page
from app.integrations.portfolio.safe_fetch import FetchResult

ROBOTS_AGENT = "AIJobInterviewSimulatorBot"
_SKIP_EXTENSIONS = (
    ".pdf", ".zip", ".gz", ".tar", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".mov", ".avi", ".css", ".js", ".json", ".xml", ".doc", ".docx", ".exe",
)  # fmt: skip
_KEYWORDS = ("project", "portfolio", "work", "about", "experience", "resume", "cv", "skill", "case")
_MAX_EXTERNAL_LINKS = 15


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...


class ExternalLink(BaseModel):
    url: str
    text: str | None = None


class PortfolioPageFact(BaseModel):
    """What one page said (untrusted text), with its source URL."""

    url: str
    title: str | None = None
    description: str | None = None
    headings: list[str] = Field(default_factory=list)
    text_excerpt: str = ""
    text_truncated: bool = False
    external_links: list[ExternalLink] = Field(default_factory=list)


class SkippedPage(BaseModel):
    url: str
    reason: str


class PortfolioSnapshot(BaseModel):
    requested_url: str
    host: str
    pages: list[PortfolioPageFact]
    skipped_pages: list[SkippedPage] = Field(default_factory=list)
    robots_txt_checked: bool = False
    fetched_at: datetime
    notice: str = (
        "Text retrieved from the public pages listed here at fetched_at, without running "
        "JavaScript. It is what the site says, not verified experience."
    )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _score(url: str) -> int:
    path = urlsplit(url).path.lower()
    return sum(1 for keyword in _KEYWORDS if keyword in path)


def _candidates(page: ParsedPage, base_host: str, base_url: str) -> list[str]:
    seen: set[str] = {base_url.split("?")[0].rstrip("/")}
    out: list[str] = []
    for link in page.links:
        parts = urlsplit(link.url)
        key = link.url.split("?")[0].rstrip("/")
        if (
            _host(link.url) != base_host
            or parts.path.lower().endswith(_SKIP_EXTENSIONS)
            or key in seen
        ):
            continue
        seen.add(key)
        out.append(link.url)
    # Pages whose paths look like projects/about/experience first; stable otherwise.
    return sorted(out, key=lambda u: -_score(u))


async def _load_robots(fetcher: PageFetcher, start: FetchResult) -> RobotFileParser | None:
    """Return parsed rules, an allow-all parser when there is no robots.txt (404), or
    ``None`` when the file exists but could not be read (then no extra pages are crawled)."""
    parts = urlsplit(start.url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser()
    try:
        result = await fetcher.fetch(robots_url)
    except PortfolioHttpError as error:
        if error.http_status in (404, 410):
            parser.parse([])  # no robots.txt: nothing is disallowed
            return parser
        return None
    except PortfolioFetchError:
        return None
    except PortfolioUrlRejectedError:
        return None
    parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
    return parser


def _fact(url: str, page: ParsedPage, base_host: str) -> PortfolioPageFact:
    external = [
        ExternalLink(url=link.url, text=link.text)
        for link in page.links
        if _host(link.url) != base_host
    ][:_MAX_EXTERNAL_LINKS]
    return PortfolioPageFact(
        url=url,
        title=page.title,
        description=page.description,
        headings=page.headings,
        text_excerpt=page.text,
        text_truncated=page.text_truncated,
        external_links=external,
    )


async def collect_portfolio(
    fetcher: PageFetcher, url: str, *, max_pages: int, now: datetime | None = None
) -> PortfolioSnapshot:
    start = await fetcher.fetch(url)  # errors here fail the whole request
    start_page = extract_page(start.body, start.url)
    host = _host(start.url)
    pages = [_fact(start.url, start_page, host)]
    skipped: list[SkippedPage] = []
    robots_checked = False

    if max_pages > 1:
        candidates = _candidates(start_page, host, start.url)
        if candidates:
            robots = await _load_robots(fetcher, start)
            robots_checked = robots is not None
            for candidate in candidates:
                if len(pages) >= max_pages:
                    break
                if robots is None:
                    skipped.append(SkippedPage(url=candidate, reason="robots.txt unavailable"))
                    break
                if not robots.can_fetch(ROBOTS_AGENT, candidate):
                    skipped.append(SkippedPage(url=candidate, reason="disallowed by robots.txt"))
                    continue
                try:
                    result = await fetcher.fetch(candidate)
                except (PortfolioFetchError, PortfolioUrlRejectedError) as error:
                    skipped.append(SkippedPage(url=candidate, reason=error.message))
                    continue
                if _host(result.url) != host:
                    skipped.append(SkippedPage(url=candidate, reason="redirected to another host"))
                    continue
                pages.append(_fact(result.url, extract_page(result.body, result.url), host))

    return PortfolioSnapshot(
        requested_url=url,
        host=host,
        pages=pages,
        skipped_pages=skipped[:20],
        robots_txt_checked=robots_checked,
        fetched_at=now or datetime.now(UTC),
    )
