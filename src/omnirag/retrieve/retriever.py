"""Hybrid retrieval: dense (embeddings) + sparse (BM25), fused with RRF,
reranked, diversified with MMR and augmented with neighbouring chunks."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from omnirag.embed.base import Embedder
from omnirag.query.parser import ParsedQuery, QueryParser
from omnirag.query.rewriter import QueryRewriter
from omnirag.query.router import ModalityRouter, RetrievalPlan
from omnirag.retrieve.bm25 import BM25Index
from omnirag.retrieve.fusion import reciprocal_rank_fusion
from omnirag.retrieve.rerank import LexicalReranker, mmr
from omnirag.store.local import LocalStore
from omnirag.store.models import ScoredChunk, SearchFilters

MODES = ("hybrid", "dense", "bm25")


@dataclass
class RetrievalResult:
    query: ParsedQuery
    plan: RetrievalPlan
    results: list[ScoredChunk] = field(default_factory=list)
    mode: str = "hybrid"


class HybridRetriever:
    def __init__(
        self,
        store: LocalStore,
        embedder: Embedder,
        rewriter: QueryRewriter | None = None,
        reranker: LexicalReranker | None = None,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        mmr_lambda: float = 0.75,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.parser = QueryParser()
        self.router = ModalityRouter()
        self.rewriter = rewriter or QueryRewriter()
        self.reranker = reranker or LexicalReranker()
        self.rrf_k = rrf_k
        self.weights = {"dense": dense_weight, "bm25": sparse_weight}
        self.mmr_lambda = mmr_lambda
        self._bm25: BM25Index | None = None
        self._bm25_revision = -1
        self._lock = threading.Lock()

    def bm25(self) -> BM25Index:
        with self._lock:
            rev = self.store.revision
            if self._bm25 is None or self._bm25_revision != rev:
                self._bm25 = BM25Index().build(
                    (c.chunk_id, c.content) for c in self.store.all_chunks()
                )
                self._bm25_revision = rev
            return self._bm25

    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: SearchFilters | None = None,
        mode: str = "hybrid",
        neighbors: int = 1,
        use_hyde: bool = False,
    ) -> RetrievalResult:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        parsed = self.parser.parse(query)
        plan = self.router.route(parsed, k=k, extra_filters=filters, neighbors=neighbors)
        text = parsed.text
        if not text.strip():
            return RetrievalResult(parsed, plan, [], mode)

        all_chunks = {c.chunk_id: c for c in self.store.all_chunks()}
        rankings: dict[str, list[str]] = {}
        dense_scores: dict[str, float] = {}
        bm25_scores: dict[str, float] = {}

        if mode in ("hybrid", "dense"):
            dense_texts = [text]
            if use_hyde:
                hypo = self.rewriter.hyde(text)
                if hypo:
                    dense_texts.append(hypo)
            for i, dt in enumerate(dense_texts):
                hits = self.store.search(
                    self.embedder.embed_query(dt), plan.candidate_k, plan.filters
                )
                name = "dense" if i == 0 else "hyde"
                rankings[name] = [h.chunk.chunk_id for h in hits]
                for h in hits:
                    dense_scores[h.chunk.chunk_id] = max(
                        dense_scores.get(h.chunk.chunk_id, -1), h.score
                    )

        if mode in ("hybrid", "bm25"):
            allowed = None
            if not plan.filters.is_empty():
                allowed = {cid for cid, c in all_chunks.items() if plan.filters.matches(c)}
            hits_bm25 = self.bm25().search(
                self.rewriter.sparse_query(parsed), plan.candidate_k, allowed
            )
            rankings["bm25"] = [cid for cid, _ in hits_bm25]
            bm25_scores = dict(hits_bm25)

        weights = {**self.weights, "hyde": self.weights["dense"] * 0.5}
        fused = reciprocal_rank_fusion(rankings, k=self.rrf_k, weights=weights)
        candidates: list[ScoredChunk] = []
        for cid, score, ranks in fused:
            chunk = all_chunks.get(cid)
            if chunk is None:
                continue
            info = {"rrf_score": round(score, 6), "ranks": ranks}
            if cid in dense_scores:
                info["dense_score"] = round(dense_scores[cid], 4)
            if cid in bm25_scores:
                info["bm25_score"] = round(bm25_scores[cid], 4)
            candidates.append(ScoredChunk(chunk, score, info))

        ranked = self.reranker.rerank(text, candidates, parsed.phrases, plan.boosts)
        pool = ranked[: max(plan.k * 3, 10)]
        embeddings = {}
        for cand in pool:
            vec = self.store.embedding_of(cand.chunk.chunk_id)
            if vec is not None:
                embeddings[cand.chunk.chunk_id] = vec
        results = mmr(pool, embeddings, plan.k, self.mmr_lambda)
        if plan.neighbors > 0:
            augment_with_neighbors(self.store, results, plan.neighbors)
        return RetrievalResult(parsed, plan, results, mode)


def augment_with_neighbors(store: LocalStore, results: list[ScoredChunk], window: int = 1) -> None:
    """Attach the chunks before/after each hit (same document) as extra context."""
    returned = {r.chunk.chunk_id for r in results}
    for r in results:
        before, after = store.neighbors(r.chunk, window)
        r.context_before = [c for c in before if c.chunk_id not in returned]
        r.context_after = [c for c in after if c.chunk_id not in returned]
