"""Builders for small, valid and invalid sample documents used in tests."""

import zipfile
from io import BytesIO

import pymupdf
from docx import Document

RESUME_LINES = [
    "Jane Doe",
    "jane.doe@example.com | +94 77 123 4567",
    "Senior Python Developer",
    "Skills: Python, FastAPI, PostgreSQL, Docker",
    "Experience: Acme Corp, Backend Engineer, 2021-2024",
    "Education: BSc Computer Science, University of Colombo",
]


def make_pdf(lines: list[str] | None = None, pages: int = 1) -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        y = 72
        for line in lines or RESUME_LINES:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
    data: bytes = document.tobytes()
    document.close()
    return data


def make_image_only_pdf() -> bytes:
    """A PDF whose only content is a picture (what a scan looks like)."""
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pixmap)
    data: bytes = document.tobytes()
    document.close()
    return data


def make_blank_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page()
    data: bytes = document.tobytes()
    document.close()
    return data


def make_encrypted_pdf(password: str = "secret") -> bytes:  # noqa: S107
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Confidential resume text")
    data: bytes = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password
    )
    document.close()
    return data


def make_docx(lines: list[str] | None = None, table: list[list[str]] | None = None) -> bytes:
    document = Document()
    for line in lines or RESUME_LINES:
        document.add_paragraph(line)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_txt(lines: list[str] | None = None) -> bytes:
    return "\n".join(lines or RESUME_LINES).encode("utf-8")


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()
