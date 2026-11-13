"""Embedding layer: one interface, several backends, plus a persistent cache.

Embedder spec strings:

* ``hashing`` / ``hashing:4096`` - built-in feature-hashing embedder (default, offline)
* ``st:BAAI/bge-small-en-v1.5`` - sentence-transformers model (``omnirag[embeddings]``)
* ``ollama:nomic-embed-text`` - Ollama embedding model
"""

from __future__ import annotations

import importlib.util

from omnirag.config import Settings, install_hint
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


MAX_HASHING_DIM = 1 << 16


def validate_spec(spec: str) -> str:
    """Check an embedder spec without loading a model; return it normalised.

    Raises :class:`EmbeddingError` for unknown backends, malformed arguments
    and backends whose optional packages are not installed.
    """
    spec = normalize_spec(spec)
    kind, sep, arg = spec.partition(":")
    arg = arg.strip()
    if kind == "hashing":
        try:
            dim = int(arg)
        except ValueError:
            raise EmbeddingError(
                f"invalid embedder spec {spec!r}: the hashing dimension must be a whole "
                "number, e.g. hashing:2048"
            ) from None
        if not 16 <= dim <= MAX_HASHING_DIM:
            raise EmbeddingError(
                f"invalid embedder spec {spec!r}: the hashing dimension must be between 16 "
                f"and {MAX_HASHING_DIM}"
            )
        return f"hashing:{dim}"
    if kind == "st":
        if sep and not arg:
            raise EmbeddingError(
                f"invalid embedder spec {spec!r}: name a model, e.g. st:BAAI/bge-small-en-v1.5"
            )
        if importlib.util.find_spec("sentence_transformers") is None:
            raise EmbeddingError(
                f"embedder {spec!r} needs sentence-transformers, which is not installed: "
                + install_hint("embeddings")
            )
        return spec if arg else "st:BAAI/bge-small-en-v1.5"
    if kind == "ollama":
        if sep and not arg:
            raise EmbeddingError(
                f"invalid embedder spec {spec!r}: name a model, e.g. ollama:nomic-embed-text"
            )
        return spec if arg else "ollama:nomic-embed-text"
    raise EmbeddingError(
        f"unknown embedder spec {spec!r} (use hashing[:dim], st:<model> or ollama:<model>)"
    )


def create_embedder(spec: str, settings: Settings | None = None) -> Embedder:
    settings = settings or Settings()
    spec = validate_spec(spec)
    kind, _, arg = spec.partition(":")
    if kind == "hashing":
        return HashingEmbedder(int(arg))
    if kind == "st":
        try:
            return SentenceTransformerEmbedder(arg)
        except EmbeddingError:
            raise
        except Exception as exc:  # model download / load failures
            raise EmbeddingError(f"could not load embedding model {arg!r}: {exc}") from exc
    return OllamaEmbedder(arg, settings.ollama_url, timeout=settings.request_timeout)


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
    "validate_spec",
]
