"""Static HTML text extraction for portfolio pages.

The HTML is parsed, never rendered: scripts, styles and embedded content are discarded
and nothing is executed. Extracted text is untrusted third-party content.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from pydantic import BaseModel, Field

MAX_TEXT_CHARS = 8000
MAX_HEADINGS = 30
MAX_LINKS = 200
_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "object",
    "embed",
    "canvas",
}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "li", "ul", "ol", "br", "tr",
    "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "figure", "nav", "aside",
}  # fmt: skip
_HEADING_TAGS = {"h1", "h2", "h3"}
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PageLink(BaseModel):
    url: str
    text: str | None = None


class ParsedPage(BaseModel):
    title: str | None = None
    description: str | None = None
    headings: list[str] = Field(default_factory=list)
    text: str = ""
    text_truncated: bool = False
    links: list[PageLink] = Field(default_factory=list)


class _Extractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self._skip_depth = 0
        self._in_title = False
        self._heading: list[str] | None = None
        self._link_text: list[str] | None = None
        self._link_href: str | None = None
        self.title_parts: list[str] = []
        self.description: str | None = None
        self.headings: list[str] = []
        self.chunks: list[str] = []
        self.links: list[PageLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k.lower(): (v or "") for k, v in attrs}
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            if name in {"description", "og:description"} and not self.description:
                self.description = attributes.get("content", "").strip() or None
            return
        if tag == "title":
            self._in_title = True
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._heading = []
        if tag == "a" and attributes.get("href"):
            self._link_href = attributes["href"]
            self._link_text = []
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            if text and len(self.headings) < MAX_HEADINGS:
                self.headings.append(text[:200])
            self._heading = None
        if tag == "a" and self._link_href is not None:
            self._finish_link()
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def _finish_link(self) -> None:
        href = (self._link_href or "").strip()
        text = " ".join("".join(self._link_text or []).split())[:120] or None
        self._link_href = None
        self._link_text = None
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            return
        try:
            absolute = urldefrag(urljoin(self._base, href))[0]
            scheme = urlsplit(absolute).scheme
        except ValueError:
            return
        if scheme in {"http", "https"} and len(self.links) < MAX_LINKS:
            self.links.append(PageLink(url=absolute[:500], text=text))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skip_depth:
            return
        self.chunks.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._link_text is not None:
            self._link_text.append(data)


def decode_html(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def extract_page(body: bytes, base_url: str) -> ParsedPage:
    extractor = _Extractor(base_url)
    extractor.feed(decode_html(body))
    extractor.close()

    raw = _CONTROL.sub("", "".join(extractor.chunks))
    lines = [_WHITESPACE.sub(" ", line).strip() for line in raw.split("\n")]
    text = _BLANK_LINES.sub("\n\n", "\n".join(line for line in lines if line is not None)).strip()
    truncated = len(text) > MAX_TEXT_CHARS
    title = " ".join("".join(extractor.title_parts).split())[:200] or None
    description = _CONTROL.sub("", extractor.description or "").strip()[:500] or None
    return ParsedPage(
        title=title,
        description=description,
        headings=extractor.headings,
        text=text[:MAX_TEXT_CHARS],
        text_truncated=truncated,
        links=extractor.links,
    )
