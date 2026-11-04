"""GitHub API access behind an interface.

Only public data is read, with the official REST API, from the configured API host
(``api.github.com``). No OAuth permissions are requested. An optional personal access
token (server-side setting) merely raises the rate limit for the same public reads.
"""

import json
import logging
import time
from typing import Any, Protocol

import httpx

from app.integrations.errors import (
    GitHubRateLimitedError,
    GitHubUnavailableError,
    GitHubUserNotFoundError,
)
from app.integrations.github.username import is_valid_repo_name, is_valid_username

logger = logging.getLogger(__name__)


class GitHubClient(Protocol):
    async def get_user(self, login: str) -> dict[str, Any]:
        """Public profile of a user. Raises ``GitHubUserNotFoundError`` if absent."""
        ...

    async def list_public_repos(self, login: str, limit: int) -> list[dict[str, Any]]:
        """Public repositories owned by the user, most recently pushed first."""
        ...

    async def get_readme(self, login: str, repo: str, max_bytes: int) -> str | None:
        """README text (truncated to ``max_bytes``), or ``None`` if the repo has none."""
        ...


class GitHubRestClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.github.com",
        token: str | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes
        self._client = client

    def __repr__(self) -> str:  # never reveal the token
        return f"GitHubRestClient(base_url={self._base_url!r})"

    # ------------------------------------------------------------------ requests

    async def get_user(self, login: str) -> dict[str, Any]:
        data = await self._get_json(f"/users/{self._safe_login(login)}")
        if not isinstance(data, dict):
            raise GitHubUnavailableError("GitHub returned an unexpected response")
        return data

    async def list_public_repos(self, login: str, limit: int) -> list[dict[str, Any]]:
        data = await self._get_json(
            f"/users/{self._safe_login(login)}/repos",
            params={
                "per_page": min(limit, 100),
                "sort": "pushed",
                "direction": "desc",
                "type": "owner",
            },
        )
        if not isinstance(data, list):
            raise GitHubUnavailableError("GitHub returned an unexpected response")
        return [item for item in data if isinstance(item, dict)][:limit]

    async def get_readme(self, login: str, repo: str, max_bytes: int) -> str | None:
        if not is_valid_repo_name(repo):
            return None
        try:
            body = await self._request(
                f"/repos/{self._safe_login(login)}/{repo}/readme",
                accept="application/vnd.github.raw+json",
                max_bytes=max_bytes,
                truncate=True,
            )
        except GitHubUserNotFoundError:
            return None  # repository without a README
        return body.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _safe_login(login: str) -> str:
        # Defence in depth: the login is interpolated into a URL path.
        if not is_valid_username(login):
            raise GitHubUserNotFoundError("GitHub user not found")
        return login

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        body = await self._request(
            path, accept="application/vnd.github+json", max_bytes=self._max_bytes, params=params
        )
        try:
            return json.loads(body)
        except ValueError:
            raise GitHubUnavailableError("GitHub returned an unexpected response") from None

    async def _request(
        self,
        path: str,
        *,
        accept: str,
        max_bytes: int,
        params: dict[str, Any] | None = None,
        truncate: bool = False,
    ) -> bytes:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-job-interview-simulator",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        client = self._client or httpx.AsyncClient()
        try:
            async with client.stream(
                "GET",
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                return await self._read_capped(response, max_bytes, truncate)
        except httpx.TimeoutException:
            raise GitHubUnavailableError("GitHub did not respond in time") from None
        except httpx.HTTPError:
            raise GitHubUnavailableError("GitHub could not be reached") from None
        finally:
            if self._client is None:
                await client.aclose()

    @staticmethod
    async def _read_capped(response: httpx.Response, max_bytes: int, truncate: bool) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                if truncate:
                    chunks.append(chunk[: len(chunk) - (total - max_bytes)])
                    break
                raise GitHubUnavailableError("GitHub's response was too large")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 300:
            return
        if status == 404:
            raise GitHubUserNotFoundError("GitHub user not found")
        remaining = response.headers.get("x-ratelimit-remaining")
        if status == 429 or (
            status == 403 and (remaining == "0" or "retry-after" in response.headers)
        ):
            raise GitHubRateLimitedError(GitHubRestClient._retry_after(response))
        if status in (401, 403):
            logger.error("GitHub rejected the request", extra={"status_code": status})
            raise GitHubUnavailableError("GitHub refused the request")
        logger.warning("GitHub returned an error", extra={"status_code": status})
        raise GitHubUnavailableError("GitHub returned an error")

    @staticmethod
    def _retry_after(response: httpx.Response) -> int | None:
        retry_after = response.headers.get("retry-after", "")
        if retry_after.isdigit():
            return int(retry_after)
        reset = response.headers.get("x-ratelimit-reset", "")
        if reset.isdigit():
            return max(1, int(reset) - int(time.time()))
        return None
