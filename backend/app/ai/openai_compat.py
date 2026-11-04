"""Provider for OpenAI and OpenAI-compatible chat-completions APIs (httpx based)."""

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.ai.errors import (
    AIProviderError,
    AIRateLimitedError,
    AIResponseError,
    AITimeoutError,
    AIUnavailableError,
)

logger = logging.getLogger(__name__)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnavailableProvider:
    """Stand-in used when no provider is configured; the rest of the app keeps working."""

    name = "none"
    model = "none"
    is_external = False

    def __init__(self, reason: str = "AI analysis is not configured on this server") -> None:
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    async def complete_json(self, *, system: str, user: str) -> str:
        raise AIUnavailableError(self._reason)


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client
        host = (urlparse(self._base_url).hostname or "").lower()
        self.is_external = host not in _LOCAL_HOSTS

    @property
    def available(self) -> bool:
        return True

    def __repr__(self) -> str:  # never reveal the key
        return f"OpenAICompatibleProvider(model={self.model!r}, base_url={self._base_url!r})"

    async def complete_json(self, *, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
        except httpx.TimeoutException:
            raise AITimeoutError("The AI provider did not respond in time") from None
        except httpx.HTTPError:
            raise AIProviderError("The AI provider could not be reached") from None

        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> str:
        status = response.status_code
        if status in (401, 403):
            logger.error("AI provider rejected credentials", extra={"status_code": status})
            raise AIUnavailableError("The AI provider rejected the configured credentials")
        if status == 429:
            retry_after = response.headers.get("retry-after", "")
            raise AIRateLimitedError(int(retry_after) if retry_after.isdigit() else None)
        if status >= 400:
            # The body is deliberately not logged: it may echo the prompt.
            logger.warning("AI provider returned an error", extra={"status_code": status})
            raise AIProviderError("The AI provider returned an error")
        try:
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIResponseError("The AI provider returned an unexpected response") from None
        if choice.get("finish_reason") == "length":
            raise AIResponseError("The AI response was cut off before it was complete")
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("The AI provider returned an empty response")
        return content
