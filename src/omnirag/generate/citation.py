"""Citation tracking with ``[n]`` markers."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from omnirag.store.models import ScoredChunk
from omnirag.textutil import truncate

_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Source:
    """A numbered source shown to the LLM and returned to the user."""

    index: int
    chunk_id: str
    doc_id: str
    source: str
    title: str
    modality: str
    score: float
    content: str
    snippet: str
    location: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    context_before: str = ""
    context_after: str = ""

    @property
    def label(self) -> str:
        name = Path(self.source).name if self.source else self.doc_id
        return f"{name}{' ' + self.location if self.location else ''}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["label"] = self.label
        return data


def describe_location(meta: dict[str, Any]) -> str:
    if "line_start" in meta:
        return f"lines {meta['line_start']}-{meta.get('line_end', meta['line_start'])}"
    if "page" in meta:
        return f"page {meta['page']}"
    if "timestamp" in meta:
        return f"@ {meta['timestamp']}"
    if "row_start" in meta:
        return f"rows {meta['row_start']}-{meta.get('row_end')}"
    if meta.get("heading"):
        return f"section '{meta['heading']}'"
    return ""


class CitationTracker:
    def __init__(self) -> None:
        self.sources: dict[int, Source] = {}

    def add(self, scored: ScoredChunk, title: str = "") -> Source:
        idx = len(self.sources) + 1
        chunk = scored.chunk
        meta = dict(chunk.metadata)
        src = Source(
            index=idx,
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            source=chunk.source,
            title=title or chunk.title or Path(chunk.source).name,
            modality=chunk.modality.value,
            score=round(float(scored.score), 4),
            content=chunk.content,
            snippet=truncate(chunk.content, 280),
            location=describe_location(meta),
            metadata=meta,
            retrieval=dict(scored.retrieval),
            context_before="\n\n".join(c.content for c in scored.context_before),
            context_after="\n\n".join(c.content for c in scored.context_after),
        )
        self.sources[idx] = src
        return src

    @staticmethod
    def extract(text: str) -> list[int]:
        """All citation numbers in order of first appearance (``[1]``, ``[2, 3]``)."""
        seen: list[int] = []
        for group in _CITE_RE.findall(text):
            for num in group.split(","):
                n = int(num.strip())
                if n not in seen:
                    seen.append(n)
        return seen

    def validate(self, text: str) -> tuple[str, list[int]]:
        """Drop citations that point at unknown sources. Returns ``(text, cited)``."""

        def fix(match: re.Match[str]) -> str:
            nums = [int(n.strip()) for n in match.group(1).split(",")]
            valid = [n for n in nums if n in self.sources]
            return "".join(f"[{n}]" for n in valid) or "\x00"

        cleaned = _CITE_RE.sub(fix, text)
        # Tidy the gap left by a removed citation ("claim [9]." -> "claim.").
        cleaned = re.sub(r"[ \t]*\x00", "", cleaned)
        return cleaned, [n for n in self.extract(cleaned) if n in self.sources]

    def bibliography(self, only: list[int] | None = None) -> str:
        lines = []
        for idx, src in sorted(self.sources.items()):
            if only is not None and idx not in only:
                continue
            lines.append(f"[{idx}] {src.title} - {src.label} ({src.modality})")
        return "\n".join(lines)
