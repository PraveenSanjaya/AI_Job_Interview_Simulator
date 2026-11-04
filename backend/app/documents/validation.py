"""Validation of uploaded documents.

Nothing here trusts the client: the filename, extension and Content-Type header
are advisory only. The accepted format is decided by inspecting the bytes, and the
extension must agree with it. Uploaded files are never executed.
"""

import hashlib
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import PurePosixPath

from fastapi import status

from app.core.exceptions import AppError, PayloadTooLargeError

MAX_ZIP_ENTRIES = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # zip-bomb guard for DOCX
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc or encrypted Office file
_SAFE_FILENAME_CHARS = re.compile(r"[^\w .()\-]", re.UNICODE)
MAX_FILENAME_LENGTH = 100


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


SUPPORTED_EXTENSIONS = {f".{fmt.value}": fmt for fmt in DocumentFormat}


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file_type"


class InvalidDocumentError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_document"


class FileTooLargeError(PayloadTooLargeError):
    code = "file_too_large"


@dataclass(frozen=True)
class ValidatedDocument:
    format: DocumentFormat
    display_name: str  # sanitised, for display only; never used as a storage path
    size_bytes: int
    sha256: str


def sanitize_filename(raw: str | None, fmt: DocumentFormat) -> str:
    """Return a safe display name: no directories, control or special characters."""
    name = (raw or "").replace("\\", "/")
    name = PurePosixPath(name).name  # drops any path components, including ../
    name = unicodedata.normalize("NFKC", name)
    name = "".join(ch for ch in name if ch.isprintable())
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = _SAFE_FILENAME_CHARS.sub("_", stem).strip(" ._")[:MAX_FILENAME_LENGTH]
    return f"{stem or 'resume'}.{fmt.value}"


def decode_text(data: bytes) -> str:
    """Decode a text file (UTF-8/UTF-16 with or without BOM, then Windows-1252)."""
    candidates: tuple[str, ...] = (
        ("utf-16",) if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp1252")
    )
    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" in text:
            break
        return text
    raise InvalidDocumentError(
        "The text file is not valid text (unsupported encoding or binary content)",
        code="invalid_text_file",
    )


def _check_docx_structure(data: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if len(infos) > MAX_ZIP_ENTRIES:
                raise InvalidDocumentError("The DOCX file has too many parts")
            if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise InvalidDocumentError("The DOCX file expands to an unreasonable size")
            if any(info.flag_bits & 0x1 for info in infos):
                raise InvalidDocumentError("The DOCX file is encrypted", code="encrypted_document")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise InvalidDocumentError("The file is not a valid DOCX document")
    except zipfile.BadZipFile:
        raise InvalidDocumentError("The file is not a valid DOCX document") from None


def _sniff(data: bytes) -> DocumentFormat | None:
    """Identify the format from content only. ``None`` means unrecognised."""
    if b"%PDF-" in data[:1024]:
        return DocumentFormat.PDF
    if data.startswith(b"PK\x03\x04"):
        return DocumentFormat.DOCX
    return None


def validate_upload(filename: str | None, data: bytes, max_bytes: int) -> ValidatedDocument:
    if not data:
        raise InvalidDocumentError("The uploaded file is empty", code="empty_file")
    if len(data) > max_bytes:
        raise FileTooLargeError(f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit")

    extension = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    expected = SUPPORTED_EXTENSIONS.get(extension)
    if expected is None:
        raise UnsupportedFileTypeError("Only PDF, DOCX and TXT files are supported")

    if data.startswith(_OLE_SIGNATURE):
        raise InvalidDocumentError(
            "Legacy Word (.doc) or password-protected Office files are not supported",
            code="unsupported_or_encrypted_document",
        )

    detected = _sniff(data)
    if expected is DocumentFormat.TXT:
        if detected is not None:
            raise InvalidDocumentError(
                "The file content does not match its .txt extension", code="content_mismatch"
            )
        decode_text(data)  # raises for binary or undecodable content
        detected = DocumentFormat.TXT
    elif detected is None:
        raise InvalidDocumentError(f"The file is not a valid {expected.value.upper()} document")
    elif detected is not expected:
        raise InvalidDocumentError(
            f"The file content does not match its .{expected.value} extension",
            code="content_mismatch",
        )

    if detected is DocumentFormat.DOCX:
        _check_docx_structure(data)

    return ValidatedDocument(
        format=detected,
        display_name=sanitize_filename(filename, detected),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
