"""Query parsing: inline filters, intent and modality hints.

Supported inline filter syntax (combinable, comma-separated values allowed)::

    modality:code        type:table      m:image,audio
    -modality:image      (exclude)
    source:*.py          file:auth       in:docs/
    lang:python          speaker:Priya   key=value (any chunk metadata)

Everything that is not a filter becomes the free-text query. Double-quoted
phrases are kept and used as exact-phrase boosts by the reranker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from omnirag.store.models import Modality, SearchFilters
from omnirag.textutil import terms


class QueryIntent(str, Enum):
    FACTUAL = "factual"
    EXPLANATORY = "explanatory"
    COMPARATIVE = "comparative"
    PROCEDURAL = "procedural"
    CODE = "code"
    SUMMARIZATION = "summarization"
    EXPLORATORY = "exploratory"


MODALITY_KEYWORDS: dict[Modality, tuple[str, ...]] = {
    Modality.IMAGE: (
        "diagram",
        "screenshot",
        "figure",
        "chart",
        "image",
        "photo",
        "picture",
        "flowchart",
        "illustration",
        "drawing",
        "visual",
    ),
    Modality.AUDIO: (
        "recording",
        "audio",
        "transcript",
        "meeting",
        "podcast",
        "talk",
        "speech",
        "said",
        "spoken",
        "discussed",
        "call",
        "decided",
        "decision",
    ),
    Modality.CODE: (
        "code",
        "function",
        "implementation",
        "implemented",
        "class",
        "method",
        "api",
        "source",
        "script",
        "snippet",
        "module",
        "def",
        "signature",
    ),
    Modality.TABLE: (
        "table",
        "dataset",
        "csv",
        "spreadsheet",
        "statistics",
        "column",
        "row",
        "schema",
        "benchmark",
        "latency",
        "average",
        "mean",
        "max",
        "min",
        "metrics",
    ),
}

_INTENT_RULES: list[tuple[QueryIntent, re.Pattern[str]]] = [
    (
        QueryIntent.COMPARATIVE,
        re.compile(r"\b(compare|comparison|versus|vs\.?|difference|better than)\b"),
    ),
    (QueryIntent.SUMMARIZATION, re.compile(r"\b(summari[sz]e|summary|overview|tl;?dr|recap)\b")),
    (
        QueryIntent.CODE,
        re.compile(r"\b(implementation|implement|function|class|method|code|snippet)\b"),
    ),
    (
        QueryIntent.PROCEDURAL,
        re.compile(r"\b(how (do|can|to|should)|steps?|set ?up|configure|install)\b"),
    ),
    (QueryIntent.EXPLANATORY, re.compile(r"\b(why|explain|how does|how is|what happens)\b")),
    (
        QueryIntent.FACTUAL,
        re.compile(r"^(what|who|when|where|which|is|are|does|did|how many|how much)\b"),
    ),
]

_TOKEN_RE = re.compile(r'(?:-?[A-Za-z_][\w.]*[:=])?"[^"]*"|\S+')
_FILTER_RE = re.compile(r"^(-?)([A-Za-z_][\w.]*)([:=])(.+)$")
_FILTER_KEYS = {
    "modality": "modality",
    "mod": "modality",
    "m": "modality",
    "type": "modality",
    "source": "source",
    "file": "source",
    "path": "source",
    "in": "source",
    "doc": "doc",
    "lang": "language",
    "language": "language",
}


@dataclass
class ParsedQuery:
    raw: str
    text: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    phrases: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    intent: QueryIntent = QueryIntent.EXPLORATORY
    modality_hints: list[Modality] = field(default_factory=list)


def detect_modality_hints(text: str) -> list[Modality]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z]+", lowered))
    hints = []
    for modality, keywords in MODALITY_KEYWORDS.items():
        if any((kw in words) if " " not in kw else (kw in lowered) for kw in keywords):
            hints.append(modality)
    return hints


def detect_intent(text: str) -> QueryIntent:
    lowered = text.lower().strip()
    for intent, pattern in _INTENT_RULES:
        if pattern.search(lowered):
            return intent
    return QueryIntent.EXPLORATORY


class QueryParser:
    def parse(self, query: str) -> ParsedQuery:
        """Split ``query`` into filters and free text.

        Raises :class:`ValueError` for an inline ``modality:`` filter naming an
        unknown modality.
        """
        tokens = [t.replace('"', "") for t in _TOKEN_RE.findall(query)]
        phrases = [p.strip() for p in re.findall(r'"([^"]+)"', query) if p.strip()]
        filters = SearchFilters()
        free: list[str] = []
        for tok in tokens:
            m = _FILTER_RE.match(tok)
            if not tok:
                continue
            if not m or "://" in tok:
                free.append(tok)
                continue
            negate, key, op, value = m.group(1) == "-", m.group(2).lower(), m.group(3), m.group(4)
            canonical = _FILTER_KEYS.get(key)
            values = [v.strip() for v in value.split(",") if v.strip()]
            if canonical == "modality":
                # Same rule as the --modality option: an unknown value is an
                # error, not a filter that silently disappears.
                mods = [Modality.parse(v) for v in values]
                if negate:
                    filters.exclude_modalities = [*(filters.exclude_modalities or []), *mods]
                else:
                    filters.modalities = [*(filters.modalities or []), *mods]
            elif canonical == "source":
                filters.sources = [*(filters.sources or []), *values]
            elif canonical == "doc":
                filters.doc_ids = [*(filters.doc_ids or []), *values]
            elif canonical == "language":
                filters.metadata["language"] = values[0].lower()
            elif op == "=" or key in {"speaker", "kind", "symbol", "section", "page"}:
                filters.metadata[key] = value
            else:
                free.append(tok)
        text = " ".join(free).strip()
        return ParsedQuery(
            raw=query,
            text=text,
            filters=filters,
            phrases=phrases,
            terms=terms(text),
            intent=detect_intent(text),
            modality_hints=detect_modality_hints(text),
        )


def parse_query(query: str) -> ParsedQuery:
    return QueryParser().parse(query)
