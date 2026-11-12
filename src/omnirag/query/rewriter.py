"""Query rewriting.

Offline (always available):

* keyword extraction (stopword removal) for the sparse retriever
* synonym / abbreviation expansion from a small built-in table

With an LLM (optional):

* HyDE: generate a short hypothetical answer passage and embed it alongside
  the query for dense retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnirag.query.parser import ParsedQuery
from omnirag.textutil import STOPWORDS, tokenize

if TYPE_CHECKING:  # pragma: no cover
    from omnirag.generate.llm import LLM

SYNONYMS: dict[str, tuple[str, ...]] = {
    "auth": ("authentication", "authorization", "login"),
    "authentication": ("auth", "login", "token"),
    "login": ("authentication", "sign in"),
    "db": ("database",),
    "database": ("db", "sql"),
    "config": ("configuration", "settings"),
    "configuration": ("config", "settings"),
    "perf": ("performance", "latency"),
    "performance": ("latency", "throughput"),
    "slow": ("latency", "performance"),
    "fast": ("latency", "performance"),
    "speed": ("latency", "performance"),
    "rate": ("throttle", "limit"),
    "throttle": ("rate limit",),
    "throttling": ("rate limit",),
    "limiter": ("rate limit", "throttle"),
    "error": ("exception", "failure"),
    "bug": ("error", "issue"),
    "deploy": ("deployment", "release"),
    "deployment": ("deploy", "release"),
    "k8s": ("kubernetes",),
    "doc": ("documentation",),
    "docs": ("documentation",),
    "meeting": ("transcript", "discussion"),
    "decided": ("decision", "agreed"),
    "decision": ("decided", "agreed"),
    "diagram": ("architecture", "figure"),
    "test": ("pytest", "testing"),
    "cache": ("caching",),
    "caching": ("cache",),
    "migration": ("migrate", "schema"),
}


class QueryRewriter:
    def __init__(self, llm: LLM | None = None, synonyms: dict | None = None) -> None:
        self.llm = llm
        self.synonyms = synonyms if synonyms is not None else SYNONYMS

    def keywords(self, text: str) -> list[str]:
        return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]

    def expand(self, text: str) -> list[str]:
        """Synonym/abbreviation expansions not already present in ``text``."""
        present = set(tokenize(text))
        extra: list[str] = []
        for tok in present:
            for syn in self.synonyms.get(tok, ()):
                if syn not in present and syn not in extra:
                    extra.append(syn)
        return extra

    def sparse_query(self, parsed: ParsedQuery) -> str:
        """Text for BM25: original keywords plus expansions."""
        base = " ".join(self.keywords(parsed.text)) or parsed.text
        expansion = self.expand(parsed.text)
        return (base + " " + " ".join(expansion)).strip()

    def hyde(self, text: str) -> str | None:
        """Hypothetical document for dense retrieval (requires an LLM)."""
        if self.llm is None:
            return None
        prompt = (
            "Write a short, factual passage (3-4 sentences) that would answer the "
            f"question below. Do not mention that it is hypothetical.\n\nQuestion: {text}"
        )
        try:
            return self.llm.complete([{"role": "user", "content": prompt}], max_tokens=200).strip()
        except Exception:
            return None
