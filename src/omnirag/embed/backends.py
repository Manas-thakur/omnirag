"""Optional neural embedding backends."""

from __future__ import annotations

import httpx
import numpy as np

from omnirag.config import install_hint
from omnirag.embed.base import Embedder, EmbeddingError, l2_normalize

_QUERY_PREFIXES = {
    "bge": "Represent this sentence for searching relevant passages: ",
    "e5": "query: ",
}


class SentenceTransformerEmbedder(Embedder):
    """Local Hugging Face model via ``sentence-transformers`` (``omnirag[embeddings]``)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", device: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed: " + install_hint("embeddings")
            ) from exc
        self.model_name = model_name
        self.name = f"st:{model_name}"
        self._model = SentenceTransformer(model_name, device=device)
        dim = self._model.get_sentence_embedding_dimension()
        self._dimension = int(dim or 0)
        lowered = model_name.lower()
        self._query_prefix = next((p for k, p in _QUERY_PREFIXES.items() if k in lowered), "")
        self._doc_prefix = "passage: " if "e5" in lowered else ""

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        vecs = self._model.encode(
            [self._doc_prefix + t for t in texts],
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return l2_normalize(np.asarray(vecs, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        vec = self._model.encode([self._query_prefix + text], normalize_embeddings=True)
        return l2_normalize(np.asarray(vec, dtype=np.float32))[0]


class OllamaEmbedder(Embedder):
    """Embeddings from a local Ollama server (``POST /api/embed``)."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        host: str = "http://localhost:11434",
        timeout: float = 120.0,
        batch_size: int = 32,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.name = f"ollama:{model}"
        self.batch_size = batch_size
        self._client = client or httpx.Client(timeout=timeout)
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = int(self.embed_documents(["dimension probe"]).shape[1])
        return self._dimension

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension or 0), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                resp = self._client.post(
                    f"{self.host}/api/embed", json={"model": self.model, "input": batch}
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
            vectors = data.get("embeddings")
            if not vectors or len(vectors) != len(batch):
                raise EmbeddingError("Ollama returned an unexpected embedding payload")
            out.extend(vectors)
        matrix = l2_normalize(np.asarray(out, dtype=np.float32))
        self._dimension = int(matrix.shape[1])
        return matrix
