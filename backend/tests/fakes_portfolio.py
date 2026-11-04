"""A real SafeFetcher wired to a fake DNS table and an in-memory web server."""

from collections.abc import Callable

import httpx

from app.integrations.portfolio.safe_fetch import SafeFetcher

PUBLIC = "93.184.216.34"

HOME = """<html><head><title>Jane Doe - Portfolio</title>
<meta name="description" content="Backend engineer"></head><body>
<h1>Jane Doe</h1><p>I build APIs with Python and FastAPI. Contact: jane.doe@example.com</p>
<a href="/projects">Projects</a><a href="https://github.com/janedoe">GitHub</a>
</body></html>"""
PROJECTS = """<html><head><title>Projects</title></head><body>
<h2>Interview Simulator</h2><p>An AI mock interview platform using FastAPI, React and PostgreSQL.</p>
</body></html>"""


class FakeWeb:
    """Maps ``host -> {path: html}``; also records requests and the DNS lookups made."""

    def __init__(
        self,
        sites: dict[str, dict[str, str]] | None = None,
        dns: dict[str, list[str]] | None = None,
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self.sites = (
            {"jane.example": {"/": HOME, "/projects": PROJECTS}} if sites is None else sites
        )
        self.dns = dns or {}
        self.custom = handler
        self.requests: list[httpx.Request] = []
        self.lookups: list[str] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        return self.dns.get(host, [PUBLIC])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.custom:
            return self.custom(request)
        site = self.sites.get(request.headers["host"])
        if site is None or request.url.path not in site:
            return httpx.Response(404)
        return httpx.Response(
            200, content=site[request.url.path].encode(), headers={"content-type": "text/html"}
        )

    def fetcher(self, **kwargs: float) -> SafeFetcher:
        return SafeFetcher(
            resolver=self.resolve,
            transport=httpx.MockTransport(self.handle),
            **kwargs,  # type: ignore[arg-type]
        )
