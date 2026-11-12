"""Persistent on-disk embedding cache (SQLite), keyed by model + text hash."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import numpy as np

from omnirag.embed.base import Embedder


def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode()).hexdigest()


class EmbeddingCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            " key TEXT PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL)"
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    def get_many(self, model: str, texts: list[str]) -> dict[int, np.ndarray]:
        keys = [_key(model, t) for t in texts]
        found: dict[str, np.ndarray] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                part = keys[i : i + 500]
                q = ",".join("?" * len(part))
                for key, dim, blob in self._conn.execute(
                    f"SELECT key, dim, vector FROM embeddings WHERE key IN ({q})", part
                ):
                    found[key] = np.frombuffer(blob, dtype=np.float32, count=dim).copy()
        result = {i: found[k] for i, k in enumerate(keys) if k in found}
        self.hits += len(result)
        self.misses += len(texts) - len(result)
        return result

    def put_many(self, model: str, texts: list[str], vectors: np.ndarray) -> None:
        rows = [
            (_key(model, t), model, int(v.shape[0]), np.asarray(v, dtype=np.float32).tobytes())
            for t, v in zip(texts, vectors, strict=True)
        ]
        with self._lock:
            self._conn.executemany("INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?)", rows)
            self._conn.commit()

    def __len__(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])

    def clear(self, model: str | None = None) -> None:
        with self._lock:
            if model:
                self._conn.execute("DELETE FROM embeddings WHERE model = ?", (model,))
            else:
                self._conn.execute("DELETE FROM embeddings")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class CachedEmbedder(Embedder):
    """Wraps an embedder so repeated texts are never embedded twice."""

    def __init__(self, inner: Embedder, cache: EmbeddingCache) -> None:
        self.inner = inner
        self.cache = cache
        self.name = inner.name

    @property
    def dimension(self) -> int:
        return self.inner.dimension

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return self.inner.embed_documents(texts)
        cached = self.cache.get_many(self.name, texts)
        missing = [i for i in range(len(texts)) if i not in cached]
        if missing:
            fresh = self.inner.embed_documents([texts[i] for i in missing])
            self.cache.put_many(self.name, [texts[i] for i in missing], fresh)
            for j, i in enumerate(missing):
                cached[i] = fresh[j]
        return np.stack([cached[i] for i in range(len(texts))]).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        # Queries may use a model-specific prefix, so they bypass the document cache.
        return self.inner.embed_query(text)
