"""Text documents: plain text, Markdown, reStructuredText, HTML and PDF."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from omnirag.chunking import RawChunk, chunk_markdown, split_text
from omnirag.ingest.base import (
    IngestContext,
    IngestError,
    Ingestor,
    ParsedDocument,
    humanize_filename,
    read_text_file,
)
from omnirag.store.models import Modality

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"([^\"]*)\")?\s*\)")
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# MDX: ES module lines and JSX components are code, not prose.
_MDX_IMPORT_RE = re.compile(r"^\s*(import|export)\s.+$", re.MULTILINE)
_MDX_COMPONENT_RE = re.compile(r"<([A-Z][\w.]*)\b([^<>]*?)/?>(?:\s*</\1>)?", re.DOTALL)
_MDX_CLOSING_RE = re.compile(r"</[A-Z][\w.]*>")
_JSX_ATTR_RE = re.compile(r"\b(?:alt|title|caption|label)=\"([^\"]+)\"")


def _clean_mdx(text: str) -> str:
    """Drop MDX imports and JSX component tags, keeping any alt/title text."""
    text = _MDX_IMPORT_RE.sub("", text)

    def component(m: re.Match) -> str:
        described = [a for a in _JSX_ATTR_RE.findall(m.group(2)) if a.strip()]
        return " ".join(described)

    text = _MDX_COMPONENT_RE.sub(component, text)
    return _MDX_CLOSING_RE.sub("", text)


_RST_UNDERLINE_RE = re.compile(r"^([=\-~^\"'`#*+])\1{2,}\s*$")


class _HTMLToText(HTMLParser):
    """Extract readable text from HTML, keeping headings as markdown headings."""

    SKIP = frozenset({"script", "style", "noscript", "template", "svg", "head"})
    BLOCK = frozenset(
        {"p", "div", "section", "article", "li", "tr", "br", "pre", "blockquote", "table"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.images: list[tuple[str, str]] = []
        self._skip = 0
        self._in_title = False
        self._heading: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag == "img":
            a = dict(attrs)
            if a.get("src"):
                self.images.append((a["src"] or "", a.get("alt") or a.get("title") or ""))
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = int(tag[1])
            self.parts.append("\n\n" + "#" * self._heading + " ")
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = None
            self.parts.append("\n\n")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data)
        if self._heading is not None:
            text = text.strip()
        if text.strip() or (self.parts and not self.parts[-1].endswith((" ", "\n"))):
            self.parts.append(text)

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_text(html: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Return ``(markdown_like_text, title, [(img_src, alt)])``."""
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    return parser.text(), parser.title.strip(), parser.images


def markdown_image_refs(text: str) -> list[tuple[str, str]]:
    """``[(target, alt_or_title)]`` for every markdown image reference."""
    refs = []
    for alt, target, title in _MD_IMAGE_RE.findall(text):
        desc = alt.strip() or (title or "").strip()
        if desc:
            refs.append((target, desc))
    return refs


def _rst_to_markdown(text: str) -> str:
    """Turn reST section underlines into markdown headings (good enough for chunking)."""
    lines = text.splitlines()
    out: list[str] = []
    levels: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and _RST_UNDERLINE_RE.match(nxt) and len(nxt.strip()) >= len(line.strip()):
            ch = nxt.strip()[0]
            if ch not in levels:
                levels.append(ch)
            out.append("#" * min(levels.index(ch) + 1, 6) + " " + line.strip())
            i += 2
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return ""


class TextIngestor(Ingestor):
    modality = Modality.TEXT

    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._ingest_pdf(path, ctx)
        raw = read_text_file(path)
        meta: dict = {"format": ext.lstrip(".") or "txt"}
        title = ""
        if ext in {".html", ".htm"}:
            text, title, _ = html_to_text(raw)
        elif ext == ".rst":
            text = _rst_to_markdown(raw)
        else:
            text = raw
        if ext in {".md", ".markdown", ".mdx"}:
            fm = _FRONT_MATTER_RE.match(text)
            if fm:
                for line in fm.group(1).splitlines():
                    if ":" in line:
                        key, _, value = line.partition(":")
                        key = key.strip().lower()
                        if key in {"title", "author", "date", "tags", "description"}:
                            meta[key] = value.strip().strip("\"'")
                text = text[fm.end() :]
            if ext == ".mdx":
                text = _clean_mdx(text)
            # Docs generators (Starlight, Docusaurus, ...) keep the page title in
            # front matter only; make it the top heading so every chunk's
            # breadcrumb says which page it came from.
            if meta.get("title") and not _first_heading(text):
                text = f"# {meta['title']}\n\n{text.lstrip()}"
        title = title or str(meta.get("title") or "") or _first_heading(text)
        title = title or humanize_filename(path).title()
        if ext in {".txt", ".text", ".log"}:
            chunks = [RawChunk(c) for c in split_text(text, ctx.chunk_size, ctx.chunk_overlap)]
        else:
            chunks = chunk_markdown(text, ctx.chunk_size, ctx.chunk_overlap)
        return ParsedDocument(path, Modality.TEXT, title, chunks, meta)

    def _ingest_pdf(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise IngestError(
                "PDF support needs the optional 'pypdf' package: pip install 'omnirag[pdf]'"
            ) from exc
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise IngestError(f"could not read PDF: {exc}") from exc
        title = ""
        try:
            if reader.metadata and reader.metadata.title:
                title = str(reader.metadata.title)
        except Exception:
            title = ""
        chunks: list[RawChunk] = []
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            for piece in split_text(page_text, ctx.chunk_size, ctx.chunk_overlap):
                chunks.append(RawChunk(piece, {"page": page_no}))
        warnings = [] if chunks else ["no extractable text (scanned PDF? OCR is not built in)"]
        return ParsedDocument(
            path,
            Modality.TEXT,
            title or humanize_filename(path).title(),
            chunks,
            {"format": "pdf", "pages": len(reader.pages)},
            warnings,
        )
