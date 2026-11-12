"""Shared ingestion types."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omnirag.chunking import RawChunk
from omnirag.config import Settings
from omnirag.store.models import Modality


class IngestError(Exception):
    """Raised when a file cannot be ingested."""


@dataclass
class IngestContext:
    """Per-run options shared by all ingestors."""

    settings: Settings = field(default_factory=Settings)
    chunk_size: int = 1200
    chunk_overlap: int = 150
    # Resolved image path -> alt texts collected from markdown/html documents.
    alt_texts: dict[str, list[str]] = field(default_factory=dict)
    # Base directory used to compute short, display-friendly relative paths.
    root: Path | None = None

    def display_path(self, path: Path) -> str:
        if self.root is not None:
            try:
                return path.resolve().relative_to(self.root.resolve()).as_posix()
            except ValueError:
                pass
        return path.name


@dataclass
class ParsedDocument:
    """Output of an ingestor: document-level info plus its chunks."""

    path: Path
    modality: Modality
    title: str
    chunks: list[RawChunk]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Ingestor(ABC):
    """Turns a file into a :class:`ParsedDocument`."""

    modality: Modality

    @abstractmethod
    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument: ...


def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def humanize_filename(path: Path) -> str:
    """``auth_flow-diagram.v2.png`` -> ``auth flow diagram v2``."""
    return " ".join(_split_name(path.stem))


def _split_name(stem: str) -> list[str]:
    spaced = re.sub(r"[_\-.]+", " ", stem)
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", spaced)
    return spaced.lower().split()
