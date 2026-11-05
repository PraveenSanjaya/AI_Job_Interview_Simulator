"""Account deletion: every user-owned record and file goes, nobody else's data is touched."""

import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import InMemoryRateLimiter
from app.models import Base, Resume, User
from app.storage.base import StorageError, new_storage_key
from app.storage.local import LocalStorage
from tests.fakes import SAMPLE_RESUME, FakeLLMProvider
from tests.fakes_github import FakeGitHubClient
from tests.helpers import DEFAULT_PASSWORD, bearer, login, register_and_login
from tests.samples import make_txt
from tests.samples_jobs import BACKEND_JOB
from tests.test_integration_analysis import LONG_README, model_reply
from tests.test_profile import full_profile

pytestmark = pytest.mark.anyio

DELETE = "/api/v1/auth/delete-account"
API = "/api/v1"


async def upload_cv(client: httpx.AsyncClient, headers: dict[str, str]) -> httpx.Response:
    return await client.post(
        f"{API}/resumes",
        headers=headers,
        files={"file": ("cv.txt", make_txt(SAMPLE_RESUME.splitlines()), "text/plain")},
    )


async def populate(app: FastAPI, client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    """Give one user data in every area of the application; returns their tokens."""
    tokens = await register_and_login(client, email)
    headers = bearer(tokens["access_token"])
    assert (await client.put(f"{API}/profile", json=full_profile(), headers=headers)).is_success

    app.state.llm_provider = FakeLLMProvider()
    for _ in range(2):  # two stored files
        uploaded = await upload_cv(client, headers)
        assert uploaded.status_code == 201, uploaded.text
    resume_id = uploaded.json()["id"]
    analysed = await client.post(f"{API}/resumes/{resume_id}/analyze", headers=headers)
    assert analysed.status_code == 200, analysed.text

    app.state.github_client = FakeGitHubClient(readmes={"interview-sim": LONG_README})
    github = await client.post(
        f"{API}/integrations/github", headers=headers, json={"username": "janedoe"}
    )
    assert github.is_success, github.text
    portfolio = await client.post(
        f"{API}/integrations/portfolio", headers=headers, json={"url": "https://jane.example/"}
    )
    assert portfolio.is_success, portfolio.text
    app.state.llm_provider = FakeLLMProvider(model_reply())
    integration = await client.post(f"{API}/integrations/analysis", headers=headers, json={})
    assert integration.status_code == 201, integration.text

    job = await client.post(
        f"{API}/jobs",
        headers=headers,
        json={"title": "Backend Engineer", "company": "Acme", "description": BACKEND_JOB},
    )
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]
    match = await client.post(f"{API}/jobs/{job_id}/match", headers=headers, json={})
    assert match.is_success, match.text

    interview = await client.post(
        f"{API}/interviews",
        headers=headers,
        json={
            "interview_types": ["technical"],
            "difficulty": "beginner",
            "question_count": 2,
            "job_id": job_id,
        },
    )
    assert interview.status_code == 201, interview.text
    sid = interview.json()["id"]
    assert (await client.post(f"{API}/interviews/{sid}/start", headers=headers)).is_success
    for _ in range(2):
        current = await client.get(f"{API}/interviews/{sid}/current-question", headers=headers)
        answered = await client.post(
            f"{API}/interviews/{sid}/answers",
            headers=headers,
            json={
                "question_id": current.json()["question"]["id"],
                "text": "I would explain it with a short example.",
            },
        )
        assert answered.status_code == 201, answered.text
    done = await client.post(f"{API}/interviews/{sid}/complete", headers=headers)
    assert done.is_success, done.text
    return tokens


async def table_counts(session: AsyncSession) -> dict[str, int]:
    session.expire_all()
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        counts[table.name] = (
            await session.execute(select(func.count()).select_from(table))
        ).scalar_one()
    return counts


def stored_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


async def test_deleting_an_account_removes_all_of_its_data_and_only_its_data(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    keep = await populate(app, client, "keep@example.com")
    counts_with_only_keeper = await table_counts(session)
    files_of_keeper = {p.name for p in stored_files(tmp_path / "storage")}
    assert len(files_of_keeper) == 2

    doomed = await populate(app, client, "doomed@example.com")
    counts_with_both = await table_counts(session)
    # The scenario really exercised every table (nothing was silently skipped).
    # pending_file_deletions is only filled when file removal fails (tested separately).
    empty = [t for t, n in counts_with_both.items() if n == 0 and t != "pending_file_deletions"]
    assert empty == [], f"populate() leaves these tables empty, so deletion is untested: {empty}"
    assert len(stored_files(tmp_path / "storage")) == 4

    response = await client.post(
        DELETE, headers=bearer(doomed["access_token"]), json={"password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True, "stored_files_removed": True}

    # Database: exactly the keeper's rows remain, table by table.
    assert await table_counts(session) == counts_with_only_keeper
    emails = (await session.execute(select(User.email))).scalars().all()
    assert emails == ["keep@example.com"]
    # Files: the keeper's two remain untouched, the deleted user's are gone.
    assert {p.name for p in stored_files(tmp_path / "storage")} == files_of_keeper

    # The other user's data is still fully usable.
    keeper_headers = bearer(keep["access_token"])
    assert (await client.get(f"{API}/resumes", headers=keeper_headers)).json() != []
    assert (await client.get(f"{API}/jobs", headers=keeper_headers)).json() != []
    assert (await client.get(f"{API}/interviews", headers=keeper_headers)).json() != []


async def test_sessions_of_a_deleted_account_stop_working(client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client, "gone@example.com")
    headers = bearer(tokens["access_token"])
    assert (await client.get(f"{API}/auth/me", headers=headers)).status_code == 200
    deleted = await client.post(DELETE, headers=headers, json={"password": DEFAULT_PASSWORD})
    assert deleted.status_code == 200

    assert (await client.get(f"{API}/auth/me", headers=headers)).status_code == 401
    refresh = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 401
    assert (await login(client, "gone@example.com")).status_code == 401


async def test_the_email_can_be_registered_again_as_a_new_empty_account(
    client: httpx.AsyncClient,
) -> None:
    tokens = await register_and_login(client, "again@example.com")
    headers = bearer(tokens["access_token"])
    await client.put(f"{API}/profile", json=full_profile(), headers=headers)
    await client.post(DELETE, headers=headers, json={"password": DEFAULT_PASSWORD})

    fresh = bearer((await register_and_login(client, "again@example.com"))["access_token"])
    profile = (await client.get(f"{API}/profile", headers=fresh)).json()
    assert profile["skills"] == [] and profile["headline"] is None


async def test_a_wrong_password_deletes_nothing(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    tokens = await populate(app, client, "careful@example.com")
    before = await table_counts(session)
    files = stored_files(tmp_path / "storage")

    response = await client.post(
        DELETE, headers=bearer(tokens["access_token"]), json={"password": "not-the-password-1"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "incorrect_password"
    assert await table_counts(session) == before
    assert stored_files(tmp_path / "storage") == files
    assert (await login(client, "careful@example.com")).status_code == 200


async def test_deletion_requires_authentication_and_a_password(client: httpx.AsyncClient) -> None:
    assert (await client.post(DELETE, json={"password": DEFAULT_PASSWORD})).status_code == 401
    tokens = await register_and_login(client, "needs@example.com")
    headers = bearer(tokens["access_token"])
    assert (await client.post(DELETE, headers=headers, json={})).status_code == 422
    assert (await client.post(DELETE, headers=headers, json={"password": ""})).status_code == 422
    assert (await client.get(f"{API}/auth/me", headers=headers)).status_code == 200


async def test_another_accounts_password_cannot_delete_this_account(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = await register_and_login(client, "a@example.com", password="Alpha-password-1")
    await register_and_login(client, "b@example.com", password="Bravo-password-2")
    response = await client.post(
        DELETE, headers=bearer(a["access_token"]), json={"password": "Bravo-password-2"}
    )
    assert response.status_code == 403
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 2


class FailingStorage(LocalStorage):
    async def delete_namespace(self, owner_id: uuid.UUID) -> int:
        raise StorageError("disk is read-only")


async def test_a_file_storage_failure_still_deletes_the_account_and_says_so(
    app: FastAPI,
    client: httpx.AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tokens = await register_and_login(client, "partial@example.com")
    headers = bearer(tokens["access_token"])
    await upload_cv(client, headers)
    app.state.storage = FailingStorage(tmp_path / "storage")

    with caplog.at_level(logging.ERROR):
        response = await client.post(DELETE, headers=headers, json={"password": DEFAULT_PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "stored_files_removed": False}
    # The database is clean: nothing in the application can reach the leftover file.
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Resume))).scalar_one() == 0
    assert any("could not be removed" in r.getMessage() for r in caplog.records)
    # The log names the opaque storage namespace, never a file name or the e-mail address.
    assert "partial@example.com" not in caplog.text and "cv.txt" not in caplog.text


async def test_a_database_failure_leaves_everything_in_place(
    client: httpx.AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = await register_and_login(client, "atomic@example.com")
    headers = bearer(tokens["access_token"])
    await upload_cv(client, headers)
    files = stored_files(tmp_path / "storage")

    async def broken_commit(self: AsyncSession) -> None:
        raise RuntimeError("database went away")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", broken_commit)
        response = await client.post(DELETE, headers=headers, json={"password": DEFAULT_PASSWORD})
    assert response.status_code == 500

    # Files were not touched because the database step came first and failed.
    assert stored_files(tmp_path / "storage") == files
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 1
    assert (await login(client, "atomic@example.com")).status_code == 200


async def test_deletion_attempts_are_rate_limited(app: FastAPI, client: httpx.AsyncClient) -> None:
    tokens = await register_and_login(client, "spam@example.com")
    headers = bearer(tokens["access_token"])
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    wrong = {"password": "wrong-password-1"}
    statuses = [
        (await client.post(DELETE, headers=headers, json=wrong)).status_code for _ in range(4)
    ]
    assert statuses == [403, 403, 429, 429]


# ------------------------------------------------------------- storage namespace


async def test_namespace_deletion_removes_only_that_owners_objects(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    mine, other = uuid.uuid4(), uuid.uuid4()
    for _ in range(3):
        await storage.put(new_storage_key(mine), b"x")
    other_key = new_storage_key(other)
    await storage.put(other_key, b"keep")

    assert await storage.delete_namespace(mine) == 3
    assert await storage.get(other_key) == b"keep"
    assert await storage.delete_namespace(mine) == 0  # idempotent
    assert not (tmp_path / mine.hex).exists()
