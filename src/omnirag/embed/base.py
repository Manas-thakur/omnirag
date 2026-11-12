"""Embedder interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend fails."""


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        norm = float(np.linalg.norm(matrix))
        return matrix / norm if norm > 0 else matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class Embedder(ABC):
    """Maps text to L2-normalised float32 vectors.

    ``name`` is a spec string (e.g. ``hashing:2048`` or ``ollama:nomic-embed-text``)
    that is persisted with each knowledge base so queries always use the same
    embedding space as ingestion.
    """

    name: str = "embedder"

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Return an ``(n, dimension)`` float32 array of normalised vectors."""

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]
