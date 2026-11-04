import json
import logging

import httpx
import pytest

from app.ai import create_llm_provider
from app.ai.errors import (
    AIProviderError,
    AIRateLimitedError,
    AIResponseError,
    AITimeoutError,
    AIUnavailableError,
)
from app.ai.openai_compat import OpenAICompatibleProvider, UnavailableProvider
from app.core.config import Settings

pytestmark = pytest.mark.anyio

SECRET_KEY = "sk-test-secret-key-do-not-log"


def provider_with(
    handler: httpx.MockTransport | None,
    base_url: str = "https://api.openai.com/v1",
) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=handler) if handler else None
    return OpenAICompatibleProvider(
        api_key=SECRET_KEY, model="test-model", base_url=base_url, client=client
    )


def ok_transport(content: str, finish_reason: str = "stop") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
        )

    return httpx.MockTransport(handler)


async def test_sends_expected_request_and_returns_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        )

    provider = provider_with(httpx.MockTransport(handler))
    assert await provider.complete_json(system="SYS", user="USR") == '{"a": 1}'
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {SECRET_KEY}"
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USR"},
    ]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AIUnavailableError),
        (403, AIUnavailableError),
        (429, AIRateLimitedError),
        (500, AIProviderError),
        (503, AIProviderError),
        (400, AIProviderError),
    ],
)
async def test_http_errors_map_to_specific_errors(status: int, expected: type[Exception]) -> None:
    provider = provider_with(httpx.MockTransport(lambda r: httpx.Response(status, text="boom")))
    with pytest.raises(expected):
        await provider.complete_json(system="s", user="u")


async def test_rate_limit_exposes_retry_after() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "17"}))
    with pytest.raises(AIRateLimitedError) as error:
        await provider_with(transport).complete_json(system="s", user="u")
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "17"}


async def test_timeout_and_network_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(AITimeoutError):
        await provider_with(httpx.MockTransport(timeout)).complete_json(system="s", user="u")
    with pytest.raises(AIProviderError):
        await provider_with(httpx.MockTransport(refused)).complete_json(system="s", user="u")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": "nope"},
    ],
)
async def test_malformed_provider_payloads_are_response_errors(payload: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    with pytest.raises(AIResponseError):
        await provider_with(transport).complete_json(system="s", user="u")


async def test_non_json_http_body_is_a_response_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(AIResponseError):
        await provider_with(transport).complete_json(system="s", user="u")


async def test_truncated_generation_is_rejected() -> None:
    with pytest.raises(AIResponseError, match="cut off"):
        await provider_with(ok_transport('{"a":', finish_reason="length")).complete_json(
            system="s", user="u"
        )


async def test_error_messages_and_logs_never_contain_prompt_or_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="echo: PROMPT-SECRET-TEXT"))
    provider = provider_with(transport)
    with caplog.at_level(logging.DEBUG), pytest.raises(AIProviderError) as error:
        await provider.complete_json(system="s", user="PROMPT-SECRET-TEXT")
    logged = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    for text in (str(error.value), logged, repr(provider)):
        assert "PROMPT-SECRET-TEXT" not in text
        assert SECRET_KEY not in text


async def test_unavailable_provider_raises_clear_error() -> None:
    provider = UnavailableProvider()
    assert provider.available is False and provider.is_external is False
    with pytest.raises(AIUnavailableError) as error:
        await provider.complete_json(system="s", user="u")
    assert error.value.status_code == 503


def test_external_flag_depends_on_endpoint() -> None:
    assert provider_with(None).is_external is True
    assert provider_with(None, base_url="http://localhost:11434/v1").is_external is False
    assert provider_with(None, base_url="http://127.0.0.1:8080/v1").is_external is False
    assert provider_with(None, base_url="https://llm.example.com/v1").is_external is True


def test_factory_defaults_to_unavailable_without_credentials() -> None:
    assert isinstance(create_llm_provider(Settings(_env_file=None)), UnavailableProvider)
    incomplete = Settings(_env_file=None, ai_provider="openai", openai_api_key=SECRET_KEY)
    provider = create_llm_provider(incomplete)
    assert isinstance(provider, UnavailableProvider) and not provider.available


def test_factory_builds_openai_provider_when_fully_configured() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="openai",
        openai_api_key=SECRET_KEY,
        openai_model="some-model",
    )
    provider = create_llm_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "some-model" and provider.available
    assert SECRET_KEY not in repr(settings)


def test_empty_ai_settings_count_as_unset() -> None:
    settings = Settings(_env_file=None, ai_provider="openai", openai_api_key="", openai_model="")
    assert settings.openai_api_key is None and settings.openai_model is None
