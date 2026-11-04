"""Fake GitHub data and client for tests. No network or credentials are used."""

from typing import Any

from app.integrations.errors import GitHubUserNotFoundError

NOW_ISO = "2026-11-01T00:00:00Z"


def api_user(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "login": "janedoe",
        "type": "User",
        "name": "Jane Doe",
        "bio": "Backend engineer. Python and FastAPI.",
        "location": "Colombo",
        "blog": "https://jane.example.com",
        "created_at": "2018-05-01T10:00:00Z",
        "followers": 12,
        "public_repos": 4,
    }
    data.update(overrides)
    return data


def api_repo(name: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "html_url": f"https://github.com/janedoe/{name}",
        "description": None,
        "homepage": None,
        "language": None,
        "topics": [],
        "stargazers_count": 0,
        "forks_count": 0,
        "fork": False,
        "archived": False,
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2026-10-15T00:00:00Z",
    }
    data.update(overrides)
    return data


DEFAULT_REPOS = [
    api_repo(
        "interview-sim",
        description="AI mock interview platform built with FastAPI and React",
        language="Python",
        topics=["fastapi", "react", "llm"],
        stargazers_count=25,
        pushed_at="2026-10-30T00:00:00Z",
    ),
    api_repo("dotfiles", language="Shell", stargazers_count=1, pushed_at="2026-03-01T00:00:00Z"),
    api_repo("forked-lib", language="Go", fork=True, stargazers_count=900),
    api_repo("old-tool", language="Python", archived=True, pushed_at="2019-01-01T00:00:00Z"),
]

DEFAULT_READMES = {
    "interview-sim": "# Interview Simulator\nBuilt with FastAPI, PostgreSQL and Docker.\n"
    "Includes JWT authentication and an AI interview engine.",
    "dotfiles": "My dotfiles.",
}


class FakeGitHubClient:
    """Scripted ``GitHubClient``; records calls."""

    def __init__(
        self,
        user: dict[str, Any] | None = None,
        repos: list[dict[str, Any]] | None = None,
        readmes: dict[str, str] | None = None,
        *,
        error: Exception | None = None,
        readme_error: Exception | None = None,
    ) -> None:
        self.user = api_user() if user is None else user
        self.repos = list(DEFAULT_REPOS) if repos is None else repos
        self.readmes = dict(DEFAULT_READMES) if readmes is None else readmes
        self.error = error
        self.readme_error = readme_error
        self.calls: list[tuple[str, ...]] = []

    async def get_user(self, login: str) -> dict[str, Any]:
        self.calls.append(("user", login))
        if self.error:
            raise self.error
        if not self.user:
            raise GitHubUserNotFoundError("GitHub user not found")
        return self.user

    async def list_public_repos(self, login: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append(("repos", login, str(limit)))
        if self.error:
            raise self.error
        return self.repos[:limit]

    async def get_readme(self, login: str, repo: str, max_bytes: int) -> str | None:
        self.calls.append(("readme", login, repo))
        if self.readme_error:
            raise self.readme_error
        text = self.readmes.get(repo)
        return text[:max_bytes] if text else None
