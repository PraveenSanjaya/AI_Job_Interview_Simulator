"""Parsing and validation of GitHub usernames and profile URLs."""

import re
from urllib.parse import urlsplit

from app.integrations.errors import InvalidGitHubUsernameError

# GitHub rules: 1-39 characters, alphanumeric or single hyphens, no leading/trailing hyphen.
_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}
# Paths on github.com that are not user profiles.
_RESERVED = {
    "orgs",
    "settings",
    "about",
    "login",
    "logout",
    "join",
    "pricing",
    "features",
    "marketplace",
    "explore",
    "topics",
    "trending",
    "sponsors",
    "notifications",
    "issues",
    "pulls",
    "search",
    "enterprise",
    "organizations",
    "apps",
    "collections",
    "events",
    "new",
}


def is_valid_username(value: str) -> bool:
    return bool(_USERNAME.fullmatch(value)) and value.lower() not in _RESERVED


def is_valid_repo_name(value: str) -> bool:
    return bool(_REPO_NAME.fullmatch(value)) and value not in {".", ".."}


def parse_github_username(raw: str) -> str:
    """Accept ``octocat``, ``@octocat`` or a github.com profile/repository URL.

    Returns the username exactly as supplied (GitHub treats case-insensitively; the
    canonical spelling comes back from the API). Raises ``InvalidGitHubUsernameError``.
    """
    text = (raw or "").strip()
    if not text or len(text) > 300:
        raise InvalidGitHubUsernameError("Enter a GitHub username or profile URL")

    candidate = text
    if "/" in text or "." in text or ":" in text:
        url = text if "://" in text else f"https://{text}"
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.username or parts.password:
            raise InvalidGitHubUsernameError("Enter a GitHub username or profile URL")
        if (parts.hostname or "").lower() not in _GITHUB_HOSTS:
            raise InvalidGitHubUsernameError("Only github.com profile URLs are supported")
        segments = [s for s in parts.path.split("/") if s]
        if not segments:
            raise InvalidGitHubUsernameError("The URL does not contain a GitHub username")
        candidate = segments[0]
    elif text.startswith("@"):
        candidate = text[1:]

    if not is_valid_username(candidate):
        raise InvalidGitHubUsernameError("That is not a valid GitHub username")
    return candidate
