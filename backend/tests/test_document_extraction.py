import pytest

from app.documents.extract import (
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
    ProcessingError,
    extract_text,
    extract_text_async,
    normalize_text,
)
from app.documents.validation import DocumentFormat
from tests.samples import (
    make_blank_pdf,
    make_docx,
    make_encrypted_pdf,
    make_image_only_pdf,
    make_pdf,
    make_txt,
)

PDF, DOCX, TXT = DocumentFormat.PDF, DocumentFormat.DOCX, DocumentFormat.TXT


def test_extracts_pdf_text_and_metadata() -> None:
    result = extract_text(make_pdf(pages=2), PDF)
    assert "jane.doe@example.com" in result.text
    assert "Senior Python Developer" in result.text
    assert result.page_count == 2
    assert result.char_count == len(result.text)
    assert result.word_count == len(result.text.split())


def test_extracts_docx_paragraphs_and_tables_in_order() -> None:
    data = make_docx(
        ["Heading line"],
        table=[["Skill", "Level"], ["Python", "Advanced"], ["SQL", "Intermediate"]],
    )
    result = extract_text(data, DOCX)
    assert result.text.splitlines()[0] == "Heading line"
    assert "Skill | Level" in result.text
    assert "Python | Advanced" in result.text
    assert result.page_count is None


def test_extracts_docx_header_text() -> None:
    from io import BytesIO

    from docx import Document

    document = Document()
    document.sections[0].header.paragraphs[0].text = "contact: header@example.com"
    document.add_paragraph("Body text of the resume")
    buffer = BytesIO()
    document.save(buffer)
    text = extract_text(buffer.getvalue(), DOCX).text
    assert "header@example.com" in text
    assert text.index("header@example.com") < text.index("Body text")


def test_extracts_txt_and_normalises_whitespace() -> None:
    raw = b"Line one  \r\n\r\n\r\n\r\nLine two\x07\n"
    result = extract_text(raw, TXT)
    assert result.text == "Line one\n\nLine two"


def test_unicode_is_preserved_and_normalised() -> None:
    result = extract_text("Café résumé 日本語".encode(), TXT)
    assert result.text == "Café résumé 日本語"


def test_image_only_pdf_reports_ocr_required() -> None:
    with pytest.raises(ProcessingError) as error:
        extract_text(make_image_only_pdf(), PDF)
    assert error.value.code == "ocr_required"
    assert "OCR" in error.value.message


def test_blank_pdf_is_empty_not_ocr() -> None:
    with pytest.raises(ProcessingError) as error:
        extract_text(make_blank_pdf(), PDF)
    assert error.value.code == "empty_document"


def test_password_protected_pdf_is_reported_as_encrypted() -> None:
    with pytest.raises(ProcessingError) as error:
        extract_text(make_encrypted_pdf(), PDF)
    assert error.value.code == "encrypted_document"


def test_corrupt_pdf_is_reported_without_crashing() -> None:
    truncated = make_pdf()[:60]
    garbage = b"%PDF-1.7\n" + b"\x00\xff" * 200
    for data in (truncated, garbage):
        with pytest.raises(ProcessingError) as error:
            extract_text(data, PDF)
        assert error.value.code in {"corrupt_document", "empty_document"}


def test_pdf_with_too_many_pages_is_rejected() -> None:
    with pytest.raises(ProcessingError) as error:
        extract_text(make_pdf(["x" * 30], pages=MAX_PDF_PAGES + 1), PDF)
    assert error.value.code == "too_many_pages"


def test_corrupt_docx_is_reported() -> None:
    from tests.samples import make_zip

    broken = make_zip({"[Content_Types].xml": b"<not-xml", "word/document.xml": b"<also-broken"})
    with pytest.raises(ProcessingError) as error:
        extract_text(broken, DOCX)
    assert error.value.code == "corrupt_document"


def test_empty_docx_and_whitespace_only_txt_are_empty_documents() -> None:
    for data, fmt in ((make_docx([""]), DOCX), (b"  \n\t \n ", TXT)):
        with pytest.raises(ProcessingError) as error:
            extract_text(data, fmt)
        assert error.value.code == "empty_document"


def test_overlong_text_is_rejected_rather_than_truncated() -> None:
    with pytest.raises(ProcessingError) as error:
        extract_text(("word " * (MAX_TEXT_CHARS // 4)).encode(), TXT)
    assert error.value.code == "document_too_long"


def test_nothing_is_fabricated_for_short_text() -> None:
    result = extract_text(make_txt(["Only one line"]), TXT)
    assert result.text == "Only one line"


def test_error_messages_never_contain_document_content() -> None:
    secret = "TOP-SECRET-CANDIDATE-DATA"
    with pytest.raises(ProcessingError) as encrypted_error:
        extract_text(make_encrypted_pdf(), PDF)
    assert secret not in encrypted_error.value.message
    with pytest.raises(ProcessingError) as corrupt_error:
        extract_text(b"%PDF-1.7 " + secret.encode() * 3, PDF)
    assert secret not in corrupt_error.value.message
    assert secret not in str(corrupt_error.value)


def test_normalize_text_is_idempotent() -> None:
    once = normalize_text("a \r\n\r\n\r\n\r\nb\x00")
    assert normalize_text(once) == once


@pytest.mark.anyio
async def test_async_wrapper_matches_sync_result() -> None:
    data = make_txt()
    assert await extract_text_async(data, TXT) == extract_text(data, TXT)
