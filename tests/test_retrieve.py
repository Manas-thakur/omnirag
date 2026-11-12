from __future__ import annotations

import numpy as np

from omnirag.retrieve import BM25Index, LexicalReranker, mmr, reciprocal_rank_fusion
from omnirag.store.models import Chunk, Modality, ScoredChunk, SearchFilters


def test_bm25_ranks_by_term_rarity_and_frequency():
    idx = BM25Index().build(
        [
            ("a", "the cat sat on the mat"),
            ("b", "the dog chased the cat around the cat tree"),
            ("c", "quantum chromodynamics of the strong force"),
        ]
    )
    hits = idx.search("cat", k=3)
    assert [h[0] for h in hits] == ["b", "a"]
    assert idx.search("quantum force")[0][0] == "c"
    assert idx.search("nothing matches") == []
    assert idx.search("cat", allowed={"a"}) == [("a", hits[1][1])]
    assert len(idx) == 3


def test_bm25_empty_index():
    assert BM25Index().build([]).search("x") == []


def test_rrf_combines_rankings():
    fused = reciprocal_rank_fusion({"dense": ["x", "y", "z"], "bm25": ["y", "x", "w"]}, k=60)
    ids = [f[0] for f in fused]
    assert set(ids[:2]) == {"x", "y"}
    assert ids[-1] in {"z", "w"}
    x = next(f for f in fused if f[0] == "x")
    assert np.isclose(x[1], 1 / 61 + 1 / 62)
    assert x[2] == {"dense": 1, "bm25": 2}


def test_rrf_weights():
    fused = reciprocal_rank_fusion({"a": ["p"], "b": ["q"]}, weights={"a": 2.0})
    assert fused[0][0] == "p"


def _sc(cid: str, content: str, score: float, modality=Modality.TEXT) -> ScoredChunk:
    return ScoredChunk(Chunk(cid, "d", content, modality, source=f"/x/{cid}.md"), score)


def test_lexical_reranker_uses_coverage_phrases_and_boosts():
    cands = [
        _sc("1", "unrelated filler text about weather", 0.9),
        _sc("2", "the token bucket refills at a fixed rate", 0.5),
        _sc("3", "diagram of the token bucket", 0.5, Modality.IMAGE),
    ]
    ranked = LexicalReranker().rerank("token bucket rate", cands, phrases=["token bucket"])
    assert ranked[0].chunk.chunk_id == "2"
    boosted = LexicalReranker().rerank(
        "token bucket",
        [
            _sc("2", "the token bucket refills", 0.5),
            _sc("3", "token bucket diagram", 0.5, Modality.IMAGE),
        ],
        boosts={Modality.IMAGE: 2.0},
    )
    assert boosted[0].chunk.chunk_id == "3"
    assert boosted[0].retrieval["modality_boost"] == 2.0


def test_mmr_prefers_diverse_results():
    cands = [_sc("a", "x", 1.0), _sc("b", "x", 0.95), _sc("c", "y", 0.9)]
    emb = {
        "a": np.array([1.0, 0.0]),
        "b": np.array([1.0, 0.0]),  # duplicate of a
        "c": np.array([0.0, 1.0]),
    }
    picked = mmr(cands, emb, k=2, lambda_param=0.5)
    assert [p.chunk.chunk_id for p in picked] == ["a", "c"]
    assert mmr(cands[:1], emb, k=3) == cands[:1]


def test_hybrid_retriever_end_to_end(demo_kb):
    result = demo_kb.search("token bucket rate limiter implementation", k=3)
    assert result.results
    top = result.results[0]
    assert "rate_limiter" in top.chunk.source or "rate-limiting" in top.chunk.source
    assert {"rrf_score", "ranks"} <= set(top.retrieval)


def test_hybrid_modes_and_filters(demo_kb):
    for mode in ("dense", "bm25", "hybrid"):
        res = demo_kb.search("redis cache latency", k=3, mode=mode)
        assert res.results, mode
    code = demo_kb.search("token", k=5, filters=SearchFilters(modalities=[Modality.CODE]))
    assert {r.chunk.modality for r in code.results} == {Modality.CODE}
    inline = demo_kb.search("modality:audio migration decision", k=3)
    assert {r.chunk.modality for r in inline.results} == {Modality.AUDIO}


def test_modality_hint_surfaces_images(demo_kb):
    res = demo_kb.search("show me the authentication flow diagram", k=3)
    assert res.results[0].chunk.modality == Modality.IMAGE


def test_neighbor_augmentation(demo_kb):
    res = demo_kb.search("refresh tokens are rotated", k=1, neighbors=1)
    hit = res.results[0]
    assert hit.context_before or hit.context_after
    assert all(c.doc_id == hit.chunk.doc_id for c in hit.context_before + hit.context_after)


def test_empty_query_returns_nothing(demo_kb):
    assert demo_kb.search("modality:code", k=3).results == []
