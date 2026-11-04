import json
import logging

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def test_app_error_uses_standard_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/not-found")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Thing not found"
    assert error["request_id"] == response.headers["x-request-id"]


async def test_unknown_route_uses_standard_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"


async def test_validation_error_lists_details(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/int/abc")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["location"] == ["path", "value"]


async def test_unexpected_error_does_not_leak_internals(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/boom")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["error"]["code"] == "internal_error"
    assert response.headers["x-request-id"]


async def test_request_id_generated_when_absent(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert len(response.headers["x-request-id"]) == 32


async def test_safe_inbound_request_id_is_preserved(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"


async def test_unsafe_inbound_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


async def test_request_log_excludes_query_string_and_headers(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.get(
            "/health/live?token=SECRET_TOKEN", headers={"Authorization": "Bearer SECRET_BEARER"}
        )
    records = [r for r in caplog.records if r.name == "app.request"]
    assert len(records) == 1
    assert records[0].__dict__["path"] == "/health/live"
    assert records[0].__dict__["status_code"] == 200
    rendered = " ".join(str(v) for v in records[0].__dict__.values())
    assert "SECRET_TOKEN" not in rendered
    assert "SECRET_BEARER" not in rendered


def test_json_formatter_emits_valid_json_with_extras() -> None:
    from app.core.logging import JsonFormatter

    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.custom_field = 42
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["custom_field"] == 42
