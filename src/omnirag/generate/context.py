"""Context assembly: pack numbered sources into a token budget."""

from __future__ import annotations

from omnirag.generate.citation import CitationTracker
from omnirag.store.models import ScoredChunk

SYSTEM_PROMPT = (
    "You are OmniRAG, a knowledge assistant that answers strictly from the provided "
    "sources. The sources may be documents, code, table summaries, image descriptions "
    "or audio transcripts. Cite every factual claim with the source number in square "
    "brackets, e.g. [1] or [2][3]. If the sources do not contain the answer, say so "
    "plainly. Be concise; use short paragraphs or bullet points and include code in "
    "fenced blocks when relevant."
)


def count_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token)."""
    return max(1, len(text) // 4)


class ContextAssembler:
    def __init__(self, max_tokens: int = 3000, include_neighbors: bool = True) -> None:
        self.max_tokens = max_tokens
        self.include_neighbors = include_neighbors

    def assemble(self, chunks: list[ScoredChunk]) -> tuple[str, CitationTracker]:
        tracker = CitationTracker()
        parts: list[str] = []
        used = 0
        for scored in chunks:
            chunk = scored.chunk
            body = chunk.content
            if self.include_neighbors and (scored.context_before or scored.context_after):
                before = "\n".join(c.content for c in scored.context_before)
                after = "\n".join(c.content for c in scored.context_after)
                with_ctx = "\n...\n".join(p for p in (before, body, after) if p)
                if used + count_tokens(with_ctx) <= self.max_tokens:
                    body = with_ctx
            idx = len(tracker.sources) + 1
            header = f"[{idx}] ({chunk.modality.value}) {chunk.source}"
            block = f"{header}\n{body}\n"
            cost = count_tokens(block)
            if parts and used + cost > self.max_tokens:
                break
            tracker.add(scored)
            parts.append(block)
            used += cost
        return "\n".join(parts), tracker


def build_messages(question: str, context: str) -> list[dict[str, str]]:
    user = (
        f"Sources:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the sources above and cite them with [n]."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
