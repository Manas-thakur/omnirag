"""Retrieval: dense + BM25 hybrid search, RRF fusion, reranking and augmentation."""

from omnirag.retrieve.bm25 import BM25Index
from omnirag.retrieve.fusion import reciprocal_rank_fusion
from omnirag.retrieve.rerank import LexicalReranker, mmr
from omnirag.retrieve.retriever import (
    HybridRetriever,
    RetrievalResult,
    augment_with_neighbors,
)

__all__ = [
    "BM25Index",
    "HybridRetriever",
    "LexicalReranker",
    "RetrievalResult",
    "augment_with_neighbors",
    "mmr",
    "reciprocal_rank_fusion",
]
