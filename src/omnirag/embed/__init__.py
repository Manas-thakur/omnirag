"""Embedding layer: one interface, several backends, plus a persistent cache.

Embedder spec strings:

* ``hashing`` / ``hashing:4096`` - built-in feature-hashing embedder (default, offline)
* ``st:BAAI/bge-small-en-v1.5`` - sentence-transformers model (``omnirag[embeddings]``)
* ``ollama:nomic-embed-text`` - Ollama embedding model
"""

from __future__ import annotations

from omnirag.config import Settings
from omnirag.embed.backends import OllamaEmbedder, SentenceTransformerEmbedder
from omnirag.embed.base import Embedder, EmbeddingError, l2_normalize
from omnirag.embed.cache import CachedEmbedder, EmbeddingCache
from omnirag.embed.hashing import HashingEmbedder


def normalize_spec(spec: str) -> str:
    spec = (spec or "hashing").strip()
    if spec == "hashing":
        return "hashing:2048"
    if spec.startswith("sentence-transformers:"):
        return "st:" + spec.split(":", 1)[1]
    return spec


def create_embedder(spec: str, settings: Settings | None = None) -> Embedder:
    settings = settings or Settings()
    spec = normalize_spec(spec)
    kind, _, arg = spec.partition(":")
    if kind == "hashing":
        return HashingEmbedder(int(arg) if arg else 2048)
    if kind == "st":
        return SentenceTransformerEmbedder(arg or "BAAI/bge-small-en-v1.5")
    if kind == "ollama":
        return OllamaEmbedder(
            arg or "nomic-embed-text", settings.ollama_url, timeout=settings.request_timeout
        )
    raise EmbeddingError(
        f"unknown embedder spec {spec!r} (use hashing, st:<model> or ollama:<model>)"
    )


__all__ = [
    "CachedEmbedder",
    "Embedder",
    "EmbeddingCache",
    "EmbeddingError",
    "HashingEmbedder",
    "OllamaEmbedder",
    "SentenceTransformerEmbedder",
    "create_embedder",
    "l2_normalize",
    "normalize_spec",
]
