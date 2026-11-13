"""Contextual index text for chunks.

A chunk is retrieved on its own, so words that only appear in its document's
name or title (for example a product name in ``anomalyguard-docs/...`` or a
page title kept in front matter) would otherwise never match it. Both the dense
embedding and the BM25 index therefore see a short header built from the
document's path and title, followed by the chunk text. The stored and displayed
chunk content is unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Bump when the header format changes: stored vectors depend on it.
CONTEXT_VERSION = 1

_SPLIT_RE = re.compile(r"[\\/]+")
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")
_SEP_RE = re.compile(r"[-_.]+")


def _path_words(path: str) -> str:
    """``anomalyguard-docs/concepts/incidents.mdx`` -> ``anomalyguard docs concepts incidents``."""
    parts = [p for p in _SPLIT_RE.split(path) if p and p not in {".", ".."}]
    if parts:
        parts[-1] = _EXT_RE.sub("", parts[-1])
    return " ".join(_SEP_RE.sub(" ", p).strip() for p in parts if p).strip()


path_words = _path_words


def context_header(metadata: Mapping[str, Any] | None) -> str:
    meta = metadata or {}
    words = _path_words(str(meta.get("path") or ""))
    title = str(meta.get("title") or "").strip()
    if title and title.lower() not in words.lower():
        words = f"{words} | {title}" if words else title
    return words


def index_text(content: str, metadata: Mapping[str, Any] | None) -> str:
    """The text a chunk is embedded and keyword-indexed with."""
    header = context_header(metadata)
    if not header:
        return content
    # Don't repeat a title the chunk already starts with (heading breadcrumbs).
    title = str((metadata or {}).get("title") or "")
    if title and content.lstrip().startswith(title):
        header = _path_words(str((metadata or {}).get("path") or "")) or header
    return f"{header}\n{content}"
