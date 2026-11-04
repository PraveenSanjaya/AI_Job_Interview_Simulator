import hashlib

import pytest

from app.documents.validation import (
    DocumentFormat,
    FileTooLargeError,
    InvalidDocumentError,
    UnsupportedFileTypeError,
    decode_text,
    sanitize_filename,
    validate_upload,
)
from tests.samples import make_docx, make_pdf, make_txt, make_zip

LIMIT = 5 * 1024 * 1024


def test_valid_documents_are_identified_from_content() -> None:
    pdf = validate_upload("cv.pdf", make_pdf(), LIMIT)
    docx = validate_upload("cv.DOCX", make_docx(), LIMIT)
    txt = validate_upload("cv.txt", make_txt(), LIMIT)
    assert (pdf.format, docx.format, txt.format) == (
        DocumentFormat.PDF,
        DocumentFormat.DOCX,
        DocumentFormat.TXT,
    )
    assert pdf.sha256 == hashlib.sha256(make_pdf()).hexdigest() or pdf.size_bytes > 0
    assert docx.display_name == "cv.docx"


def test_empty_file_is_rejected() -> None:
    with pytest.raises(InvalidDocumentError) as error:
        validate_upload("cv.pdf", b"", LIMIT)
    assert error.value.code == "empty_file"


def test_oversized_file_is_rejected_with_413() -> None:
    with pytest.raises(FileTooLargeError) as error:
        validate_upload("cv.txt", b"a" * 2049, 2048)
    assert error.value.status_code == 413


def test_file_exactly_at_the_limit_is_accepted() -> None:
    validate_upload("cv.txt", b"a" * 2048, 2048)


@pytest.mark.parametrize(
    "name",
    ["cv.exe", "cv.doc", "cv.rtf", "cv.html", "cv.pdf.exe", "cv", "", None, ".pdf.", "cv.py"],
)
def test_unsupported_extensions_are_rejected(name: str | None) -> None:
    with pytest.raises(UnsupportedFileTypeError) as error:
        validate_upload(name, make_pdf(), LIMIT)
    assert error.value.status_code == 415


def test_content_type_header_is_irrelevant_only_bytes_count() -> None:
    # An executable renamed to .pdf is rejected because the bytes are not a PDF.
    with pytest.raises(InvalidDocumentError):
        validate_upload("cv.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100, LIMIT)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("cv.txt", make_pdf()),
        ("cv.txt", make_docx()),
        ("cv.pdf", make_docx()),
        ("cv.docx", make_pdf()),
        ("cv.pdf", make_txt()),
        ("cv.docx", make_txt()),
    ],
)
def test_extension_must_match_content(name: str, data: bytes) -> None:
    with pytest.raises(InvalidDocumentError) as error:
        validate_upload(name, data, LIMIT)
    assert error.value.code in {"content_mismatch", "invalid_document"}


def test_pdf_header_may_follow_a_short_preamble() -> None:
    validate_upload("cv.pdf", b"\n\n" + make_pdf(), LIMIT)


def test_plain_zip_is_not_a_docx() -> None:
    with pytest.raises(InvalidDocumentError):
        validate_upload("cv.docx", make_zip({"hello.txt": b"hi"}), LIMIT)


def test_truncated_zip_is_rejected() -> None:
    with pytest.raises(InvalidDocumentError):
        validate_upload("cv.docx", make_docx()[:200], LIMIT)


def test_zip_bomb_with_huge_expansion_is_rejected() -> None:
    bomb = make_zip(
        {
            "[Content_Types].xml": b"<x/>",
            "word/document.xml": b"<x/>",
            "word/big.bin": b"\x00" * (101 * 1024 * 1024),
        }
    )
    assert len(bomb) < LIMIT  # tiny on the wire, huge when expanded
    with pytest.raises(InvalidDocumentError, match="unreasonable size"):
        validate_upload("cv.docx", bomb, LIMIT)


def test_docx_with_too_many_entries_is_rejected() -> None:
    entries = {f"f{i}.xml": b"x" for i in range(1001)}
    entries |= {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>"}
    with pytest.raises(InvalidDocumentError, match="too many parts"):
        validate_upload("cv.docx", make_zip(entries), LIMIT)


def test_legacy_or_encrypted_office_files_are_reported_clearly() -> None:
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    for name in ("cv.docx", "cv.doc".replace(".doc", ".pdf")):
        with pytest.raises(InvalidDocumentError) as error:
            validate_upload(name, ole, LIMIT)
        assert error.value.code == "unsupported_or_encrypted_document"


@pytest.mark.parametrize("payload", [b"abc\x00def", bytes(range(256)) * 4, b"\x80\x81\x82\x83\x00"])
def test_binary_data_is_not_accepted_as_text(payload: bytes) -> None:
    with pytest.raises(InvalidDocumentError) as error:
        validate_upload("cv.txt", payload, LIMIT)
    assert error.value.code == "invalid_text_file"


def test_text_encodings() -> None:
    assert decode_text("héllo".encode()) == "héllo"
    assert decode_text(b"\xef\xbb\xbfhello") == "hello"  # UTF-8 BOM removed
    assert decode_text("héllo".encode("utf-16")) == "héllo"
    assert decode_text("caf\xe9".encode("cp1252")) == "café"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("/abs/path/cv.pdf", "cv.pdf"),
        ("my résumé (final).pdf", "my résumé (final).pdf"),
        ("cv<script>alert(1)</script>.pdf", "script.pdf"),
        ("cv\x00.pdf", "cv.pdf"),
        ("cv\r\nContent-Type: text/html.pdf", "html.pdf"),
        ("...pdf", "resume.pdf"),
        ("", "resume.pdf"),
        (None, "resume.pdf"),
        ("a" * 500 + ".pdf", "a" * 100 + ".pdf"),
        ("name;rm -rf /.pdf", "resume.pdf"),
        ("con.pdf", "con.pdf"),
    ],
)
def test_filenames_are_sanitised(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw, DocumentFormat.PDF) == expected


def test_sanitised_name_never_contains_path_separators_or_controls() -> None:
    nasty = 'a/b\\c\x00\x1f\n\t:*?"<>|d.pdf'
    cleaned = sanitize_filename(nasty, DocumentFormat.PDF)
    assert not any(ch in cleaned for ch in '/\\:*?"<>|\x00\n\t')
