"""Small, dependency-free text utilities shared by BM25, the hashing embedder,
the query parser and the extractive answerer."""

from __future__ import annotations

import re

STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both but by can could did do does doing down during
    each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just me more most my myself no nor
    not now of off on once only or other our ours ourselves out over own same she
    should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves
    show tell explain describe give find please let us get also within use used
    using done like one two may might must shall
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[`])")


def stem(token: str) -> str:
    """A deliberately conservative plural stemmer (predictable > clever)."""
    if len(token) <= 3 or token.isdigit():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is", "os")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. CamelCase and snake_case identifiers are split
    into their parts (and the joined identifier is kept as well)."""
    out: list[str] = []
    for word in _WORD_RE.findall(text):
        parts = _CAMEL_RE.findall(word)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
        out.append(word.lower())
    return out


def terms(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Normalised index/search terms: tokenized, stopwords removed, stemmed."""
    result = []
    for tok in tokenize(text):
        if not keep_stopwords and tok in STOPWORDS:
            continue
        if len(tok) == 1 and not tok.isdigit():
            continue
        result.append(stem(tok))
    return result


def split_sentences(text: str) -> list[str]:
    """Split text into sentences/lines suitable for extractive answering."""
    sentences: list[str] = []
    for block in re.split(r"\n\s*\n|\n(?=\s*[-*+]\s)|\n(?=#+\s)", text):
        block = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if not block:
            continue
        sentences.extend(s.strip() for s in _SENTENCE_RE.split(block) if s.strip())
    return sentences


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "..."
