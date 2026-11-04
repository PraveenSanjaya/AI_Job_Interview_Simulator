"""Text extraction from validated PDF, DOCX and TXT documents.

Extraction never returns empty or invented text silently: image-only (scanned)
PDFs raise ``ocr_required``, password-protected PDFs raise ``encrypted_document``,
and so on. OCR itself is a possible later capability and is not attempted here.

Extraction is synchronous and CPU-bound; call ``extract_text_async`` from async code.
"""

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO

import pymupdf
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.documents.validation import DocumentFormat, InvalidDocumentError, decode_text

MAX_PDF_PAGES = 50
MAX_TEXT_CHARS = 200_000
# A resume with fewer visible characters than this has no usable text layer.
MIN_TEXT_CHARS = 20

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


class ProcessingError(Exception):
    """Extraction failed for a reason worth telling the user (stable ``code``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    format: DocumentFormat
    page_count: int | None
    char_count: int
    word_count: int


def normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL_CHARS.sub("", text)
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _extract_pdf(data: bytes) -> tuple[str, int]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ProcessingError("corrupt_document", "The PDF could not be read") from None
    try:
        if document.needs_pass:
            raise ProcessingError(
                "encrypted_document", "The PDF is password-protected; upload an unprotected copy"
            )
        page_count = document.page_count
        if page_count == 0:
            raise ProcessingError("empty_document", "The PDF has no pages")
        if page_count > MAX_PDF_PAGES:
            raise ProcessingError("too_many_pages", f"The PDF has more than {MAX_PDF_PAGES} pages")
        parts: list[str] = []
        has_images = False
        try:
            for index in range(page_count):
                page = document.load_page(index)
                parts.append(page.get_text("text"))
                has_images = has_images or bool(page.get_images())
        except Exception:
            raise ProcessingError("corrupt_document", "The PDF could not be read") from None
    finally:
        document.close()

    text = normalize_text("\n".join(parts))
    if len(re.sub(r"\s", "", text)) < MIN_TEXT_CHARS:
        if has_images:
            raise ProcessingError(
                "ocr_required",
                "The PDF appears to be a scan or image-only document with no text layer. "
                "OCR is required (not yet supported); upload a text-based PDF or DOCX.",
            )
        raise ProcessingError("empty_document", "The PDF contains no readable text")
    return text, page_count


def _table_text(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            value = cell.text.strip()
            if value and value not in cells:  # merged cells repeat their text
                cells.append(value)
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_docx(data: bytes) -> str:
    try:
        document = Document(BytesIO(data))
        blocks: list[str] = []
        for section in document.sections:  # contact details often live in the header
            header = "\n".join(p.text for p in section.header.paragraphs if p.text.strip())
            if header and header not in blocks:
                blocks.append(header)
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                blocks.append(Paragraph(child, document).text)
            elif child.tag == qn("w:tbl"):
                blocks.append(_table_text(Table(child, document)))
    except Exception:
        raise ProcessingError("corrupt_document", "The DOCX could not be read") from None
    return normalize_text("\n".join(blocks))


def extract_text(data: bytes, fmt: DocumentFormat) -> ExtractionResult:
    page_count: int | None = None
    if fmt is DocumentFormat.PDF:
        text, page_count = _extract_pdf(data)
    elif fmt is DocumentFormat.DOCX:
        text = _extract_docx(data)
    else:
        try:
            text = normalize_text(decode_text(data))
        except InvalidDocumentError:
            raise ProcessingError("corrupt_document", "The text file could not be read") from None

    if not text:
        raise ProcessingError("empty_document", "The document contains no readable text")
    if len(text) > MAX_TEXT_CHARS:
        raise ProcessingError(
            "document_too_long", f"The document has more than {MAX_TEXT_CHARS:,} characters"
        )
    return ExtractionResult(
        text=text,
        format=fmt,
        page_count=page_count,
        char_count=len(text),
        word_count=len(text.split()),
    )


async def extract_text_async(data: bytes, fmt: DocumentFormat) -> ExtractionResult:
    return await asyncio.to_thread(extract_text, data, fmt)
