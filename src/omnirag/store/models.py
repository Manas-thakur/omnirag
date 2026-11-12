"""Core data models shared across the pipeline."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    CODE = "code"
    TABLE = "table"

    @classmethod
    def parse(cls, value: str | Modality) -> Modality:
        if isinstance(value, Modality):
            return value
        key = value.strip().lower()
        alias = _MODALITY_ALIASES.get(key, key)
        try:
            return cls(alias)
        except ValueError as exc:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"unknown modality {value!r} (expected one of: {valid})") from exc


_MODALITY_ALIASES = {
    "txt": "text",
    "doc": "text",
    "docs": "text",
    "document": "text",
    "documents": "text",
    "img": "image",
    "images": "image",
    "picture": "image",
    "diagram": "image",
    "diagrams": "image",
    "transcript": "audio",
    "transcripts": "audio",
    "speech": "audio",
    "meeting": "audio",
    "source": "code",
    "tables": "table",
    "data": "table",
    "csv": "table",
}


@dataclass
class Document:
    """One ingested source file."""

    doc_id: str
    source: str
    modality: Modality
    content_hash: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    chunk_count: int = 0


@dataclass
class Chunk:
    """A retrievable unit of text (or text *description* of non-text content)."""

    chunk_id: str
    doc_id: str
    content: str
    modality: Modality
    source: str = ""
    position: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: np.ndarray | None = None

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or "")


@dataclass
class ScoredChunk:
    """A chunk plus how (and how well) it was retrieved."""

    chunk: Chunk
    score: float
    retrieval: dict[str, Any] = field(default_factory=dict)
    context_before: list[Chunk] = field(default_factory=list)
    context_after: list[Chunk] = field(default_factory=list)


@dataclass
class SearchFilters:
    """Metadata filters applied before ranking.

    * ``modalities``: keep only these modalities
    * ``exclude_modalities``: drop these modalities
    * ``sources``: glob patterns (``*.py``) or substrings matched against the source path
    * ``doc_ids``: restrict to specific documents
    * ``metadata``: exact-match key/value pairs on chunk metadata (case-insensitive strings)
    """

    modalities: list[Modality] | None = None
    exclude_modalities: list[Modality] | None = None
    sources: list[str] | None = None
    doc_ids: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.modalities
            or self.exclude_modalities
            or self.sources
            or self.doc_ids
            or self.metadata
        )

    def merge(self, other: SearchFilters | None) -> SearchFilters:
        if other is None:
            return self

        def _join(a: list | None, b: list | None) -> list | None:
            if not a and not b:
                return None
            return list(dict.fromkeys([*(a or []), *(b or [])]))

        return SearchFilters(
            modalities=_join(self.modalities, other.modalities),
            exclude_modalities=_join(self.exclude_modalities, other.exclude_modalities),
            sources=_join(self.sources, other.sources),
            doc_ids=_join(self.doc_ids, other.doc_ids),
            metadata={**self.metadata, **other.metadata},
        )

    def matches(self, chunk: Chunk) -> bool:
        if self.modalities and chunk.modality not in self.modalities:
            return False
        if self.exclude_modalities and chunk.modality in self.exclude_modalities:
            return False
        if self.doc_ids and chunk.doc_id not in self.doc_ids:
            return False
        if self.sources and not any(_source_matches(chunk.source, p) for p in self.sources):
            return False
        for key, expected in self.metadata.items():
            actual = chunk.metadata.get(key)
            if actual is None:
                return False
            if str(actual).lower() != str(expected).lower():
                return False
        return True


def _source_matches(source: str, pattern: str) -> bool:
    norm_source = source.replace("\\", "/").lower()
    norm_pattern = pattern.replace("\\", "/").lower()
    if any(ch in norm_pattern for ch in "*?["):
        name = norm_source.rsplit("/", 1)[-1]
        return fnmatch.fnmatch(norm_source, norm_pattern) or fnmatch.fnmatch(name, norm_pattern)
    return norm_pattern in norm_source
