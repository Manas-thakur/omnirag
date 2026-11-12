"""Lightweight rerankers that need no model downloads.

* :class:`LexicalReranker` combines the fused retrieval score with query-term
  coverage, exact-phrase matches and per-modality boosts from the router.
* :func:`mmr` (Maximal Marginal Relevance) trades relevance for diversity so
  near-duplicate chunks do not crowd out other sources.
"""

from __future__ import annotations

import numpy as np

from omnirag.store.models import Modality, ScoredChunk
from omnirag.textutil import terms


class LexicalReranker:
    def __init__(
        self,
        retrieval_weight: float = 0.55,
        coverage_weight: float = 0.35,
        phrase_weight: float = 0.10,
        title_weight: float = 0.10,
    ) -> None:
        self.retrieval_weight = retrieval_weight
        self.coverage_weight = coverage_weight
        self.phrase_weight = phrase_weight
        self.title_weight = title_weight

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        phrases: list[str] | None = None,
        boosts: dict[Modality, float] | None = None,
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        q_terms = set(terms(query))
        phrases = [p.lower() for p in (phrases or []) if p.strip()]
        boosts = boosts or {}
        top = max(c.score for c in candidates) or 1.0
        for cand in candidates:
            chunk_terms = set(terms(cand.chunk.content))
            coverage = len(q_terms & chunk_terms) / len(q_terms) if q_terms else 0.0
            lowered = cand.chunk.content.lower()
            phrase = (sum(p in lowered for p in phrases) / len(phrases)) if phrases else 0.0
            head = " ".join(
                [
                    cand.chunk.source,
                    str(cand.chunk.metadata.get("heading", "")),
                    str(cand.chunk.metadata.get("symbol", "")),
                ]
            )
            title_hit = len(q_terms & set(terms(head))) / len(q_terms) if q_terms else 0.0
            base = (
                self.retrieval_weight * (cand.score / top)
                + self.coverage_weight * coverage
                + self.phrase_weight * phrase
                + self.title_weight * title_hit
            )
            boost = boosts.get(cand.chunk.modality, 1.0)
            cand.retrieval.update(
                {
                    "fused_score": cand.score,
                    "coverage": round(coverage, 3),
                    "modality_boost": boost,
                }
            )
            cand.score = base * boost
        return sorted(candidates, key=lambda c: -c.score)


def mmr(
    candidates: list[ScoredChunk],
    embeddings: dict[str, np.ndarray],
    k: int,
    lambda_param: float = 0.75,
) -> list[ScoredChunk]:
    """Select ``k`` candidates balancing relevance (``score``) and novelty."""
    if len(candidates) <= 1:
        return candidates[:k]
    top = max(c.score for c in candidates) or 1.0
    remaining = list(candidates)
    selected: list[ScoredChunk] = []
    while remaining and len(selected) < k:
        best, best_val = None, -np.inf
        for cand in remaining:
            rel = cand.score / top
            vec = embeddings.get(cand.chunk.chunk_id)
            sim = 0.0
            if vec is not None and selected:
                sims = [
                    float(np.dot(vec, embeddings[s.chunk.chunk_id]))
                    for s in selected
                    if s.chunk.chunk_id in embeddings
                ]
                sim = max(sims) if sims else 0.0
            val = lambda_param * rel - (1 - lambda_param) * sim
            if val > best_val:
                best, best_val = cand, val
        assert best is not None
        selected.append(best)
        remaining.remove(best)
    return selected
