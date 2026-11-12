"""Okapi BM25, implemented from scratch with an inverted index."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from omnirag.textutil import terms as default_terms


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75, analyzer=default_terms) -> None:
        self.k1 = k1
        self.b = b
        self.analyzer = analyzer
        self.doc_ids: list[str] = []
        self.doc_len: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = {}
        self.idf: dict[str, float] = {}
        self.avgdl = 0.0

    def __len__(self) -> int:
        return len(self.doc_ids)

    def build(self, docs: Iterable[tuple[str, str]]) -> BM25Index:
        self.doc_ids, self.doc_len, self.postings = [], [], {}
        for idx, (doc_id, text) in enumerate(docs):
            toks = self.analyzer(text)
            self.doc_ids.append(doc_id)
            self.doc_len.append(len(toks))
            for term, tf in Counter(toks).items():
                self.postings.setdefault(term, []).append((idx, tf))
        n = len(self.doc_ids)
        self.avgdl = (sum(self.doc_len) / n) if n else 0.0
        # BM25+ style non-negative IDF.
        self.idf = {
            term: math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for term, plist in self.postings.items()
        }
        return self

    def score(self, query: str) -> dict[int, float]:
        scores: dict[int, float] = {}
        if not self.doc_ids:
            return scores
        for term, qtf in Counter(self.analyzer(query)).items():
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf[term]
            for idx, tf in plist:
                norm = self.k1 * (1 - self.b + self.b * self.doc_len[idx] / (self.avgdl or 1))
                scores[idx] = scores.get(idx, 0.0) + qtf * idf * tf * (self.k1 + 1) / (tf + norm)
        return scores

    def search(
        self, query: str, k: int = 10, allowed: set[str] | None = None
    ) -> list[tuple[str, float]]:
        scored = [
            (self.doc_ids[i], s)
            for i, s in self.score(query).items()
            if allowed is None or self.doc_ids[i] in allowed
        ]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]
