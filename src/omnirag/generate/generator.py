"""Answer generation: context assembly -> LLM (or extractive fallback) -> citation check."""

from __future__ import annotations

import time
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
