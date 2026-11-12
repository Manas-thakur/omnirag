"""Answer generation: context assembly -> LLM (or extractive fallback) -> citation check."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from omnirag.generate.citation import Source
from omnirag.generate.context import ContextAssembler, build_messages
from omnirag.generate.extractive import ExtractiveAnswerer
from omnirag.generate.llm import LLM, LLMError
from omnirag.store.models import ScoredChunk


@dataclass
class Answer:
    question: str
    text: str
    sources: list[Source] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)
    backend: str = "extractive"
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)

    @property
    def cited_sources(self) -> list[Source]:
        return [s for s in self.sources if s.index in self.cited]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.text,
            "backend": self.backend,
            "cited": self.cited,
            "sources": [s.to_dict() for s in self.sources],
            "warnings": self.warnings,
            "timings": self.timings,
            "query": self.query,
        }


class AnswerGenerator:
    def __init__(
        self,
        llm: LLM | None = None,
        max_context_tokens: int = 3000,
        max_tokens: int = 800,
        temperature: float = 0.1,
        fallback: bool = True,
    ) -> None:
        self.llm = llm
        self.assembler = ContextAssembler(max_context_tokens)
        self.extractive = ExtractiveAnswerer()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.fallback = fallback

    def stream(self, question: str, results: list[ScoredChunk]) -> Iterator[tuple[str, Any]]:
        """Streaming variant of :meth:`generate`.

        Yields ``("sources", list[Source])`` once retrieval context is packed,
        then ``("delta", str)`` pieces of the answer as they are produced, and
        finally ``("answer", Answer)`` with the citation-checked text. Without an
        LLM the extractive answer is emitted sentence by sentence.
        """
        start = time.perf_counter()
        context, tracker = self.assembler.assemble(results)
        sources = list(tracker.sources.values())
        yield "sources", sources
        warnings: list[str] = []
        backend = "extractive"
        parts: list[str] = []
        first_token_ms: float | None = None
        if self.llm is not None and sources:
            try:
                for piece in self.llm.stream(
                    build_messages(question, context),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ):
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - start) * 1000
                    parts.append(piece)
                    yield "delta", piece
                backend = self.llm.name
            except LLMError as exc:
                if not self.fallback:
                    raise
                if parts:
                    backend = self.llm.name
                    warnings.append(f"{exc}; the answer may be incomplete")
                else:
                    warnings.append(f"{exc}; fell back to the extractive answerer")
        if not parts:
            text = self.extractive.answer(question, sources)
            for piece in _pieces(text):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                parts.append(piece)
                yield "delta", piece
        text, cited = tracker.validate("".join(parts).strip())
        if sources and not cited and backend != "extractive":
            warnings.append("the model answer contains no valid [n] citations")
        timings = {"generate_ms": round((time.perf_counter() - start) * 1000, 1)}
        if first_token_ms is not None:
            timings["first_token_ms"] = round(first_token_ms, 1)
        yield (
            "answer",
            Answer(
                question=question,
                text=text,
                sources=sources,
                cited=cited,
                backend=backend,
                warnings=warnings,
                timings=timings,
            ),
        )

    def generate(self, question: str, results: list[ScoredChunk]) -> Answer:
        start = time.perf_counter()
        context, tracker = self.assembler.assemble(results)
        sources = list(tracker.sources.values())
        warnings: list[str] = []
        backend = "extractive"
        text: str | None = None
        if self.llm is not None and sources:
            try:
                text = self.llm.complete(
                    build_messages(question, context),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                backend = self.llm.name
            except LLMError as exc:
                if not self.fallback:
                    raise
                warnings.append(f"{exc}; fell back to the extractive answerer")
        if text is None:
            text = self.extractive.answer(question, sources)
        text, cited = tracker.validate(text)
        if sources and not cited and backend != "extractive":
            warnings.append("the model answer contains no valid [n] citations")
        return Answer(
            question=question,
            text=text,
            sources=sources,
            cited=cited,
            backend=backend,
            warnings=warnings,
            timings={"generate_ms": round((time.perf_counter() - start) * 1000, 1)},
        )


def _pieces(text: str) -> Iterator[str]:
    """Split text into small runs (words plus trailing whitespace) for streaming."""
    yield from (m.group(0) for m in re.finditer(r"\S+\s*|\s+", text))
