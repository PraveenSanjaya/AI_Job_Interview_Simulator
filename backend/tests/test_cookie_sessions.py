"""Cookie-based sessions: the refresh token lives only in an HttpOnly cookie, and the
endpoints that accept it are protected against cross-site request forgery."""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.core.tokens import hash_refresh_token
from app.models import RefreshToken
from tests.conftest import TEST_JWT_SECRET, build_app
from tests.fakes import SAMPLE_RESUME
from tests.helpers import DEFAULT_PASSWORD, bearer, login, register, register_and_login
from tests.samples import make_txt

pytestmark = pytest.mark.anyio

AUTH = "/api/v1/auth"
ORIGIN = "http://localhost:5173"
REFRESH_MAX_AGE = 7 * 24 * 3600


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, jwt_secret_key=TEST_JWT_SECRET, **overrides)


def set_cookie_headers(response: httpx.Response) -> dict[str, str]:
    """Raw ``Set-Cookie`` header of each cookie, keyed by cookie name."""
    return {raw.split("=", 1)[0]: raw for raw in response.headers.get_list("set-cookie")}


def attributes(raw: str) -> dict[str, str]:
    parts = [p.strip() for p in raw.split(";")][1:]
    return {p.split("=", 1)[0].lower(): (p.split("=", 1)[1] if "=" in p else "") for p in parts}


def csrf_headers(client: httpx.AsyncClient, origin: str = ORIGIN) -> dict[str, str]:
    return {"Origin": origin, "X-CSRF-Token": client.cookies.get("csrf_token") or ""}


def client_for(app: Any) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def cookie_login(client: httpx.AsyncClient, email: str = "ada@example.com") -> httpx.Response:
    assert (await register(client, email)).status_code == 202
    response = await login(client, email)
    assert response.status_code == 200, response.text
    return response


async def cookie_refresh(
    client: httpx.AsyncClient, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.post(
        f"{AUTH}/refresh", headers=csrf_headers(client) if headers is None else headers
    )


async def all_tokens(session: AsyncSession) -> list[RefreshToken]:
    session.expire_all()
    result = await session.execute(select(RefreshToken).order_by(RefreshToken.created_at))
    return list(result.scalars())


# --- login: cookie flags and body ---------------------------------------------------------


async def test_login_sets_an_httponly_refresh_cookie_and_keeps_it_out_of_the_body(
    client: httpx.AsyncClient,
) -> None:
    response = await cookie_login(client)
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    refresh_value = client.cookies.get("refresh_token")
    assert refresh_value
    assert refresh_value not in response.text

    refresh = attributes(set_cookie_headers(response)["refresh_token"])
    assert "httponly" in refresh
    assert refresh["samesite"].lower() == "strict"
    assert refresh["path"] == "/api/v1/auth"  # narrow: not sent to the rest of the API
    assert int(refresh["max-age"]) == REFRESH_MAX_AGE
    assert "domain" not in refresh  # host-only cookie


async def test_csrf_cookie_is_readable_by_script_and_strict(client: httpx.AsyncClient) -> None:
    response = await cookie_login(client)
    csrf = attributes(set_cookie_headers(response)["csrf_token"])
    assert "httponly" not in csrf  # the front end must read it to echo it in the header
    assert csrf["samesite"].lower() == "strict"
    assert int(csrf["max-age"]) == REFRESH_MAX_AGE
    assert "domain" not in csrf


async def test_cookies_are_not_secure_in_development_and_secure_when_configured(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    for settings, expected in (
        (make_settings(), False),
        (make_settings(cookie_secure=True), True),
    ):
        async with client_for(build_app(db_engine, settings, tmp_path / "storage")) as c:
            await register(c)
            cookies = set_cookie_headers(await login(c))
            for name in ("refresh_token", "csrf_token"):
                assert ("secure" in attributes(cookies[name])) is expected


async def test_cookie_names_are_configurable(db_engine: AsyncEngine, tmp_path: Path) -> None:
    settings = make_settings(refresh_cookie_name="sid", csrf_cookie_name="xsrf")
    async with client_for(build_app(db_engine, settings, tmp_path / "storage")) as c:
        await register(c)
        assert set(set_cookie_headers(await login(c))) == {"sid", "xsrf"}
        refreshed = await c.post(
            f"{AUTH}/refresh", headers={"Origin": ORIGIN, "X-CSRF-Token": c.cookies["xsrf"]}
        )
        assert refreshed.status_code == 200


# --- refresh ------------------------------------------------------------------------------


async def test_refresh_with_the_cookie_rotates_it_and_keeps_the_token_out_of_the_body(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    login_response = await cookie_login(client)
    first = client.cookies.get("refresh_token") or ""
    response = await cookie_refresh(client)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["access_token"] != login_response.json()["access_token"]

    second = client.cookies.get("refresh_token")
    assert second and second != first
    assert second not in response.text
    refresh = attributes(set_cookie_headers(response)["refresh_token"])
    assert "httponly" in refresh and int(refresh["max-age"]) == REFRESH_MAX_AGE

    old, new = await all_tokens(session)
    assert old.token_hash == hash_refresh_token(first)
    assert old.revoked_at is not None and new.revoked_at is None
    assert new.family_id == old.family_id


async def test_the_old_refresh_token_cannot_be_reused_and_replay_revokes_the_family(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await cookie_login(client)
    first = client.cookies.get("refresh_token") or ""
    assert (await cookie_refresh(client)).status_code == 200  # rotates; the cookie is now new

    client.cookies.set("refresh_token", first, path="/api/v1/auth")  # attacker replays it
    replay = await cookie_refresh(client)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"
    assert all(t.revoked_at is not None for t in await all_tokens(session))  # whole family

    # The failed refresh told the browser to drop its dead cookies.
    assert attributes(set_cookie_headers(replay)["refresh_token"])["max-age"] == "0"


async def test_missing_refresh_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    await cookie_login(client)
    headers = csrf_headers(client)
    client.cookies.delete("refresh_token", path="/api/v1/auth")
    response = await cookie_refresh(client, headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_invalid_refresh_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    await cookie_login(client)
    client.cookies.set("refresh_token", "not-a-real-token", path="/api/v1/auth")
    response = await cookie_refresh(client)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


# --- CSRF and origin checks ---------------------------------------------------------------


async def test_a_valid_csrf_token_and_trusted_origin_are_accepted(
    client: httpx.AsyncClient,
) -> None:
    await cookie_login(client)
    assert (await cookie_refresh(client)).status_code == 200


async def test_a_missing_csrf_header_is_rejected_and_the_session_survives(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await cookie_login(client)
    response = await cookie_refresh(client, {"Origin": ORIGIN})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert all(t.revoked_at is None for t in await all_tokens(session))  # nothing consumed


async def test_a_missing_csrf_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    await cookie_login(client)
    headers = csrf_headers(client)
    client.cookies.delete("csrf_token", path="/")
    response = await cookie_refresh(client, headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_a_wrong_csrf_token_is_rejected(client: httpx.AsyncClient) -> None:
    await cookie_login(client)
    response = await cookie_refresh(client, {"Origin": ORIGIN, "X-CSRF-Token": "forged"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:5174", "null"])
async def test_an_untrusted_origin_is_rejected_even_with_a_valid_csrf_token(
    client: httpx.AsyncClient, origin: str
) -> None:
    await cookie_login(client)
    response = await cookie_refresh(client, csrf_headers(client, origin))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_a_request_with_neither_origin_nor_referer_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    await cookie_login(client)
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}
    assert (await cookie_refresh(client, headers)).status_code == 403


async def test_the_referer_is_used_when_origin_is_absent(client: httpx.AsyncClient) -> None:
    await cookie_login(client)
    token = client.cookies.get("csrf_token") or ""
    good = await cookie_refresh(client, {"Referer": f"{ORIGIN}/dashboard", "X-CSRF-Token": token})
    assert good.status_code == 200
    token = client.cookies.get("csrf_token") or ""
    bad = await cookie_refresh(client, {"Referer": "https://evil.example/x", "X-CSRF-Token": token})
    assert bad.status_code == 403


async def test_extra_cors_origins_are_trusted(db_engine: AsyncEngine, tmp_path: Path) -> None:
    settings = make_settings(cors_allowed_origins=["http://127.0.0.1:5173"])
    async with client_for(build_app(db_engine, settings, tmp_path / "storage")) as c:
        await cookie_login(c)
        response = await cookie_refresh(c, csrf_headers(c, "http://127.0.0.1:5173"))
        assert response.status_code == 200


# --- logout -------------------------------------------------------------------------------


async def test_logout_revokes_the_session_and_clears_the_cookies(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    login_response = await cookie_login(client)
    headers = bearer(login_response.json()["access_token"])
    assert (await client.get(f"{AUTH}/me", headers=headers)).status_code == 200

    response = await client.post(f"{AUTH}/logout", headers=csrf_headers(client))
    assert response.status_code == 204
    cookies = set_cookie_headers(response)
    for name, path in (("refresh_token", "/api/v1/auth"), ("csrf_token", "/")):
        cleared = attributes(cookies[name])
        assert cleared["max-age"] == "0" and cleared["path"] == path
    assert client.cookies.get("refresh_token") is None

    assert all(t.revoked_at is not None for t in await all_tokens(session))
    assert (await client.get(f"{AUTH}/me", headers=headers)).status_code == 401  # access too


async def test_logout_with_the_cookie_needs_csrf(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await cookie_login(client)
    response = await client.post(f"{AUTH}/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.cookies.get("refresh_token")  # a forged logout did not end the session
    assert all(t.revoked_at is None for t in await all_tokens(session))


async def test_logout_without_a_session_is_idempotent(client: httpx.AsyncClient) -> None:
    assert (await client.post(f"{AUTH}/logout")).status_code == 204


# --- account deletion ---------------------------------------------------------------------


async def test_account_deletion_clears_the_authentication_cookies(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    login_response = await cookie_login(client)
    response = await client.post(
        f"{AUTH}/delete-account",
        headers=bearer(login_response.json()["access_token"]),
        json={"password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 200
    cookies = set_cookie_headers(response)
    assert attributes(cookies["refresh_token"])["max-age"] == "0"
    assert attributes(cookies["csrf_token"])["max-age"] == "0"
    assert client.cookies.get("refresh_token") is None
    assert await all_tokens(session) == []


async def test_account_deletion_still_removes_stored_files(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    login_response = await cookie_login(client)
    headers = bearer(login_response.json()["access_token"])
    upload = await client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("cv.txt", make_txt(SAMPLE_RESUME.splitlines()), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    assert [p for p in (tmp_path / "storage").rglob("*") if p.is_file()]

    response = await client.post(
        f"{AUTH}/delete-account", headers=headers, json={"password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["stored_files_removed"] is True
    assert [p for p in (tmp_path / "storage").rglob("*") if p.is_file()] == []


# --- legacy request-body refresh ----------------------------------------------------------


def legacy_client(db_engine: AsyncEngine, tmp_path: Path, *, allow: bool) -> httpx.AsyncClient:
    settings = make_settings(allow_legacy_refresh_body=allow)
    return client_for(build_app(db_engine, settings, tmp_path / "storage"))


async def test_legacy_body_refresh_works_when_enabled(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    async with legacy_client(db_engine, tmp_path, allow=True) as c:
        tokens = await register_and_login(c)
        c.cookies.clear()  # a legacy browser: only the token it kept in localStorage
        response = await c.post(f"{AUTH}/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert response.status_code == 200
        assert "refresh_token" not in response.json()
        assert c.cookies.get("refresh_token")  # migrated to a cookie


async def test_legacy_body_refresh_is_rejected_when_disabled_and_cannot_skip_csrf(
    db_engine: AsyncEngine, tmp_path: Path, session: AsyncSession
) -> None:
    async with legacy_client(db_engine, tmp_path, allow=False) as c:
        tokens = await register_and_login(c)
        body = {"refresh_token": tokens["refresh_token"]}
        c.cookies.clear()

        # No CSRF proof: a body token does not bypass the cookie-path checks.
        assert (await c.post(f"{AUTH}/refresh", json=body)).status_code == 403
        # With CSRF proof it still does not authenticate, because there is no cookie.
        c.cookies.set("csrf_token", "t")
        proven = await c.post(
            f"{AUTH}/refresh", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": "t"}
        )
        assert proven.status_code == 401
        assert proven.json()["error"]["code"] == "invalid_refresh_token"
        assert all(t.revoked_at is None for t in await all_tokens(session))  # never used

        # A body token does not log the session out either (logout is an idempotent no-op).
        assert (await c.post(f"{AUTH}/logout", json=body)).status_code == 204
        assert all(t.revoked_at is None for t in await all_tokens(session))


async def test_a_body_token_cannot_override_the_cookie_when_legacy_is_disabled(
    db_engine: AsyncEngine, tmp_path: Path, session: AsyncSession
) -> None:
    async with legacy_client(db_engine, tmp_path, allow=False) as c:
        await register_and_login(c)
        response = await c.post(
            f"{AUTH}/refresh", json={"refresh_token": "attacker-chosen"}, headers=csrf_headers(c)
        )
        assert response.status_code == 200  # the legitimate cookie was used, not the body
        assert len(await all_tokens(session)) == 2


# --- production configuration -------------------------------------------------------------


def production(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"app_env": "production", "frontend_url": "https://app.example.com"}
    return make_settings(**{**base, **overrides})


def test_production_cookies_are_secure_by_default() -> None:
    assert production().refresh_cookie_secure is True


def test_production_rejects_insecure_cookies() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        production(cookie_secure=False)


def test_production_rejects_http_origins() -> None:
    with pytest.raises(ValueError, match="https"):
        production(frontend_url="http://app.example.com")
    with pytest.raises(ValueError, match="https"):
        production(cors_allowed_origins=["http://other.example.com"])


def test_production_rejects_wildcard_credentialed_cors() -> None:
    with pytest.raises(ValueError, match="Wildcard"):
        production(cors_allowed_origins=["*"])


async def test_credentialed_cors_is_limited_to_explicit_origins(
    client: httpx.AsyncClient,
) -> None:
    allowed = await client.get("/health/live", headers={"Origin": ORIGIN})
    assert allowed.headers["access-control-allow-origin"] == ORIGIN  # never "*"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    other = await client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


# --- concurrency --------------------------------------------------------------------------


@pytest.mark.parametrize("parallel", [2, 6])
async def test_concurrent_cookie_refreshes_rotate_exactly_once(
    concurrent_client: httpx.AsyncClient, parallel: int
) -> None:
    await cookie_login(concurrent_client)
    headers = csrf_headers(concurrent_client)
    refresh_cookie = concurrent_client.cookies.get("refresh_token") or ""
    csrf_cookie = concurrent_client.cookies.get("csrf_token") or ""
    concurrent_client.cookies.clear()

    async def one() -> httpx.Response:
        # Every request carries the same (old) refresh cookie, as parallel tabs would.
        return await concurrent_client.post(
            f"{AUTH}/refresh",
            headers={
                **headers,
                "Cookie": f"refresh_token={refresh_cookie}; csrf_token={csrf_cookie}",
            },
        )

    responses = await asyncio.gather(*(one() for _ in range(parallel)))
    assert sorted(r.status_code for r in responses) == [200] + [401] * (parallel - 1)
    for failed in (r for r in responses if r.status_code == 401):
        assert failed.json()["error"]["code"] == "invalid_refresh_token"
        assert "refresh_token" in set_cookie_headers(failed)  # told to drop the dead cookie
