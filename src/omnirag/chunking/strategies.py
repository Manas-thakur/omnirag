"""Chunking strategies.

All sizes are measured in characters (roughly 4 characters per token), which
keeps the implementation dependency-free and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

_SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ", " ")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class RawChunk:
    """A chunk produced by an ingestor, before it gets ids and embeddings."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def fixed_size_chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Sliding character window. Simple and predictable; used as a last resort."""
    if size <= 0:
        raise ValueError("size must be positive")
    overlap = max(0, min(overlap, size - 1))
    text = text.strip()
    if not text:
        return []
    step = size - overlap
    return [text[i : i + size].strip() for i in range(0, max(len(text) - overlap, 1), step)]


def _split_recursive(text: str, max_chars: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    if not separators:
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    sep, rest = separators[0], separators[1:]
    if sep not in text:
        return _split_recursive(text, max_chars, rest)
    pieces = text.split(sep)
    out: list[str] = []
    for i, piece in enumerate(pieces):
        # Keep the separator attached so sentences/lines read naturally.
        piece = piece + (sep if i < len(pieces) - 1 and sep.strip() else "")
        if len(piece) > max_chars:
            out.extend(_split_recursive(piece, max_chars, rest))
        elif piece.strip():
            out.append(piece)
    return out


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def split_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Recursive splitter: paragraphs, then lines, sentences, clauses, words.

    Pieces are greedily packed up to ``max_chars``; consecutive chunks share up
    to ``overlap`` characters of trailing context.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    body = max(max_chars - overlap, max_chars // 2)
    pieces = _split_recursive(text, body, _SEPARATORS)
    packed: list[str] = []
    current = ""
    for piece in pieces:
        joiner = "" if not current or current.endswith(("\n", " ")) else "\n\n"
        if current and len(current) + len(joiner) + len(piece) > body:
            packed.append(current.strip())
            current = piece
        else:
            current = current + joiner + piece if current else piece
    if current.strip():
        packed.append(current.strip())
    if overlap <= 0 or len(packed) == 1:
        return packed
    result = [packed[0]]
    for prev, nxt in pairwise(packed):
        tail = _tail(prev, overlap).strip()
        result.append(f"{tail} {nxt}".strip() if tail else nxt)
    return result


def markdown_sections(text: str) -> list[tuple[list[str], str]]:
    """Split markdown into ``(heading_path, body)`` sections.

    Headings inside fenced code blocks are ignored.
    """
    sections: list[tuple[list[str], str]] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body or (path and not sections):
            sections.append(([title for _, title in path], body))
        buf.clear()

    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, title))
            continue
        buf.append(line)
    flush()
    return [(p, b) for p, b in sections if b]


def chunk_markdown(text: str, max_chars: int = 1200, overlap: int = 150) -> list[RawChunk]:
    """Heading-aware markdown chunking.

    Each chunk is prefixed with its heading breadcrumb so that it stays
    self-describing when retrieved on its own.
    """
    chunks: list[RawChunk] = []
    sections = markdown_sections(text)
    if not sections:
        return [RawChunk(c) for c in split_text(text, max_chars, overlap)]
    for headings, body in sections:
        crumb = " > ".join(headings)
        budget = max(max_chars - len(crumb) - 2, max_chars // 2)
        for piece in split_text(body, budget, overlap):
            content = f"{crumb}\n\n{piece}" if crumb else piece
            meta: dict[str, Any] = {}
            if headings:
                meta["heading"] = crumb
                meta["section"] = headings[-1]
            chunks.append(RawChunk(content, meta))
    return chunks


def chunk_lines(
    lines: list[str], max_lines: int = 60, overlap: int = 5, start_line: int = 1
) -> list[tuple[int, int, str]]:
    """Window over lines (used for code). Returns ``(first, last, text)`` with
    1-based inclusive line numbers."""
    if not lines:
        return []
    overlap = max(0, min(overlap, max_lines - 1))
    out = []
    i = 0
    while i < len(lines):
        window = lines[i : i + max_lines]
        text = "\n".join(window).strip("\n")
        if text.strip():
            out.append((start_line + i, start_line + i + len(window) - 1, text))
        if i + max_lines >= len(lines):
            break
        i += max_lines - overlap
    return out
