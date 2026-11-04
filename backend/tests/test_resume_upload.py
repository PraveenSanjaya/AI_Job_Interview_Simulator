from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import Resume
from tests.conftest import TEST_JWT_SECRET
from tests.helpers import bearer, register_and_login
from tests.samples import (
    make_docx,
    make_encrypted_pdf,
    make_image_only_pdf,
    make_pdf,
    make_txt,
)

pytestmark = pytest.mark.anyio

RESUMES = "/api/v1/resumes"
PUBLIC_FIELDS = {
    "id",
    "display_name",
    "file_format",
    "size_bytes",
    "status",
    "failure_stage",
    "error_code",
    "error_message",
    "page_count",
    "char_count",
    "word_count",
    "has_analysis",
    "created_at",
    "extracted_at",
    "analyzed_at",
}


async def headers_for(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    return bearer((await register_and_login(client, email))["access_token"])


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    data: bytes,
    name: str = "cv.pdf",
    content_type: str = "application/octet-stream",
) -> httpx.Response:
    return await client.post(RESUMES, headers=headers, files={"file": (name, data, content_type)})


def stored_files(app: FastAPI, tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "storage").rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    ("name", "data", "fmt", "pages"),
    [
        ("cv.pdf", make_pdf(pages=2), "pdf", 2),
        ("cv.docx", make_docx(), "docx", None),
        ("cv.txt", make_txt(), "txt", None),
    ],
)
async def test_supported_formats_upload_and_extract(
    client: httpx.AsyncClient, name: str, data: bytes, fmt: str, pages: int | None
) -> None:
    headers = await headers_for(client)
    response = await upload(client, headers, data, name)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == PUBLIC_FIELDS
    assert body["status"] == "extracted"
    assert body["file_format"] == fmt
    assert body["page_count"] == pages
    assert body["char_count"] > 50
    assert body["failure_stage"] is None and body["error_code"] is None
    assert body["has_analysis"] is False


async def test_response_never_exposes_paths_hashes_or_text(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    body = (await upload(client, headers, make_txt(), "cv.txt")).text
    resume = (await session.execute(select(Resume))).scalar_one()
    for secret in (resume.storage_key, resume.sha256, "jane.doe@example.com", "storage"):
        assert secret not in body


async def test_file_is_stored_under_a_server_generated_name(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    data = make_pdf()
    await upload(client, headers, data, name="../../../evil name.pdf")
    files = stored_files(app, tmp_path)
    assert len(files) == 1
    assert files[0].read_bytes() == data
    assert len(files[0].name) == 32 and "evil" not in str(files[0])
    resume = (await session.execute(select(Resume))).scalar_one()
    assert resume.display_name == "evil name.pdf"  # directory parts dropped
    assert files[0].resolve().is_relative_to((tmp_path / "storage").resolve())


async def test_client_content_type_is_ignored(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    ok = await upload(client, headers, make_pdf(), content_type="text/plain")
    assert ok.status_code == 201
    fake = await upload(
        client, headers, b"MZ\x90\x00" + b"\x00" * 64, content_type="application/pdf"
    )
    assert fake.status_code == 422


@pytest.mark.parametrize("name", ["cv.exe", "cv.doc", "script.py", "noextension"])
async def test_unsupported_types_are_rejected_and_not_stored(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, name: str
) -> None:
    headers = await headers_for(client)
    response = await upload(client, headers, make_pdf(), name)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert stored_files(app, tmp_path) == []


async def test_empty_file_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await upload(client, headers, b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"


@pytest.mark.parametrize(
    "case",
    [
        ("cv.pdf", b"not a pdf at all"),
        ("cv.docx", make_pdf()),
        ("cv.txt", make_pdf()),
        ("cv.docx", b"PK\x03\x04garbage"),
    ],
)
async def test_malformed_or_mismatched_documents_are_rejected(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, case: tuple[str, bytes]
) -> None:
    headers = await headers_for(client)
    response = await upload(client, headers, case[1], case[0])
    assert response.status_code == 422
    assert stored_files(app, tmp_path) == []


async def test_oversized_file_is_rejected_by_the_service_limit(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, jwt_secret_key=TEST_JWT_SECRET, max_upload_bytes=2048
    )
    headers = await headers_for(client)
    response = await upload(client, headers, b"a" * 3000, "cv.txt")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert stored_files(app, tmp_path) == []


async def test_huge_body_is_rejected_by_the_middleware_before_parsing(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)
    body = b"a" * (5 * 1024 * 1024 + 200 * 1024)
    response = await upload(client, headers, body, "cv.txt")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_streamed_body_without_content_length_is_also_limited(
    client: httpx.AsyncClient,
) -> None:
    headers = await headers_for(client)

    async def chunks() -> Any:
        yield (
            b"--x\r\n"
            b'Content-Disposition: form-data; name="file"; filename="a.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
        )
        for _ in range(7):
            yield b"a" * (1024 * 1024)

    response = await client.post(
        RESUMES,
        headers={**headers, "Content-Type": "multipart/form-data; boundary=x"},
        content=chunks(),
    )
    assert response.status_code == 413


async def test_scanned_pdf_is_stored_but_flagged_as_needing_ocr(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await upload(client, headers, make_image_only_pdf())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_stage"] == "extraction"
    assert body["error_code"] == "ocr_required"
    assert "OCR" in body["error_message"]
    assert body["char_count"] is None


async def test_encrypted_pdf_is_flagged(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    body = (await upload(client, headers, make_encrypted_pdf())).json()
    assert body["status"] == "failed"
    assert body["error_code"] == "encrypted_document"


async def test_text_that_extracts_to_nothing_is_flagged_empty(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    body = (await upload(client, headers, b"   \n\t\n  ", "cv.txt")).json()
    assert body["status"] == "failed"
    assert body["error_code"] == "empty_document"


async def test_upload_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.post(RESUMES, files={"file": ("cv.pdf", make_pdf())})
    assert response.status_code == 401
    for method, path in (("get", RESUMES), ("get", f"{RESUMES}/{'0' * 32}"), ("delete", RESUMES)):
        assert (await getattr(client, method)(path)).status_code in (401, 405)


async def test_missing_file_field_is_a_validation_error(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    response = await client.post(RESUMES, headers=headers, data={"x": "y"})
    assert response.status_code == 422


async def test_list_and_get_return_only_own_resumes_newest_first(
    client: httpx.AsyncClient,
) -> None:
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    first = (await upload(client, ada, make_txt(), "first.txt")).json()
    second = (await upload(client, ada, make_txt(), "second.txt")).json()
    await upload(client, bob, make_txt(), "bobs.txt")

    listed = (await client.get(RESUMES, headers=ada)).json()
    assert [r["display_name"] for r in listed] == ["second.txt", "first.txt"]
    assert (await client.get(f"{RESUMES}/{first['id']}", headers=ada)).json()["id"] == first["id"]
    assert second["id"] in {r["id"] for r in listed}
    assert [r["display_name"] for r in (await client.get(RESUMES, headers=bob)).json()] == [
        "bobs.txt"
    ]


async def test_other_users_resume_is_indistinguishable_from_missing(
    client: httpx.AsyncClient,
) -> None:
    ada = await headers_for(client, "ada@example.com")
    bob = await headers_for(client, "bob@example.com")
    resume_id = (await upload(client, ada, make_txt(), "cv.txt")).json()["id"]

    stolen = await client.get(f"{RESUMES}/{resume_id}", headers=bob)
    missing = await client.get(f"{RESUMES}/00000000-0000-0000-0000-000000000000", headers=bob)
    assert stolen.status_code == missing.status_code == 404
    assert stolen.json()["error"]["code"] == missing.json()["error"]["code"] == "resume_not_found"
    assert (await client.delete(f"{RESUMES}/{resume_id}", headers=bob)).status_code == 404
    assert (await client.get(f"{RESUMES}/{resume_id}", headers=ada)).status_code == 200  # intact


async def test_malformed_resume_id_is_a_validation_error(client: httpx.AsyncClient) -> None:
    headers = await headers_for(client)
    assert (await client.get(f"{RESUMES}/not-a-uuid", headers=headers)).status_code == 422


async def test_delete_removes_record_and_stored_file(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path, session: AsyncSession
) -> None:
    headers = await headers_for(client)
    resume_id = (await upload(client, headers, make_pdf())).json()["id"]
    assert len(stored_files(app, tmp_path)) == 1

    assert (await client.delete(f"{RESUMES}/{resume_id}", headers=headers)).status_code == 204
    assert stored_files(app, tmp_path) == []
    assert (await session.execute(select(Resume))).first() is None
    assert (await client.get(f"{RESUMES}/{resume_id}", headers=headers)).status_code == 404
    assert (await client.delete(f"{RESUMES}/{resume_id}", headers=headers)).status_code == 404


async def test_database_failure_does_not_leave_an_orphan_file(
    app: FastAPI,
    client: httpx.AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await headers_for(client)

    async def failing_commit(self: AsyncSession) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    response = await upload(client, headers, make_pdf())
    assert response.status_code == 500
    assert stored_files(app, tmp_path) == []


async def test_upload_is_rate_limited_per_user(app: FastAPI, client: httpx.AsyncClient) -> None:
    from app.core.rate_limit import InMemoryRateLimiter

    headers = await headers_for(client)
    app.state.rate_limiter = InMemoryRateLimiter(2, 60)
    codes = [(await upload(client, headers, make_txt(), "cv.txt")).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


async def test_logs_never_contain_resume_content_or_filenames(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    headers = await headers_for(client)
    with caplog.at_level(logging.DEBUG):
        await upload(client, headers, make_txt(), "jane-doe-secret-name.txt")
        await upload(client, headers, make_image_only_pdf(), "scan.pdf")
    logged = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    for secret in ("jane.doe@example.com", "+94 77 123 4567", "jane-doe-secret-name", "Acme Corp"):
        assert secret not in logged
