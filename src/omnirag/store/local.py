"""Local persistent store: SQLite for documents, chunks, metadata and vectors.

Vectors are stored as float32 BLOBs and loaded into a single in-memory numpy
matrix for exact (brute-force) cosine search. That is plenty fast for the
tens-of-thousands-of-chunks scale of a personal knowledge base, and keeps the
store a single portable file.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from omnirag.store.models import Chunk, Document, Modality, ScoredChunk, SearchFilters

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source TEXT NOT NULL UNIQUE,
    modality TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    modality TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, position);
CREATE INDEX IF NOT EXISTS idx_chunks_modality ON chunks(modality);
CREATE INDEX IF NOT EXISTS idx_documents_modality ON documents(modality);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class StoreStats:
    documents: int
    chunks: int
    by_modality: dict[str, int] = field(default_factory=dict)
    documents_by_modality: dict[str, int] = field(default_factory=dict)
    dimension: int | None = None
    storage_bytes: int = 0
    avg_chunk_chars: float = 0.0
    last_updated: str | None = None


@dataclass
class _Matrix:
    revision: int
    chunks: list[Chunk]
    matrix: np.ndarray
    index: dict[str, int]


class LocalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._matrix: _Matrix | None = None

    # ------------------------------------------------------------------ meta
    def _get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._get_meta("revision", "0") or 0)

    def _bump(self) -> None:
        self._set_meta("revision", str(self.revision + 1))
        self._set_meta("updated_at", utcnow())

    @property
    def dimension(self) -> int | None:
        with self._lock:
            value = self._get_meta("dimension")
        return int(value) if value else None

    # ------------------------------------------------------------- documents
    @staticmethod
    def _row_to_doc(row: tuple) -> Document:
        return Document(
            doc_id=row[0],
            source=row[1],
            modality=Modality(row[2]),
            content_hash=row[3],
            title=row[4] or "",
            metadata=json.loads(row[5] or "{}"),
            created_at=row[6],
            updated_at=row[7],
            chunk_count=row[8],
        )

    _DOC_COLS = "doc_id, source, modality, content_hash, title, metadata, created_at, updated_at, chunk_count"

    def get_document(self, doc_id: str) -> Document | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._DOC_COLS} FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
        return self._row_to_doc(row) if row else None

    def get_document_by_source(self, source: str) -> Document | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._DOC_COLS} FROM documents WHERE source = ?", (source,)
            ).fetchone()
        return self._row_to_doc(row) if row else None

    def list_documents(self, modality: Modality | None = None) -> list[Document]:
        sql = f"SELECT {self._DOC_COLS} FROM documents"
        args: tuple = ()
        if modality is not None:
            sql += " WHERE modality = ?"
            args = (modality.value,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY source", args).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def upsert_document(self, doc: Document, chunks: list[Chunk]) -> None:
        """Insert or replace a document and all of its chunks atomically."""
        dims = {int(c.embedding.shape[0]) for c in chunks if c.embedding is not None}
        if len(dims) > 1:
            raise ValueError("chunks have inconsistent embedding dimensions")
        with self._lock:
            current_dim = self.dimension
            if dims and current_dim is not None and dims != {current_dim}:
                raise ValueError(
                    f"embedding dimension {dims.pop()} does not match store dimension {current_dim}; "
                    "rebuild the knowledge base to change embedders"
                )
            now = utcnow()
            existing = self.get_document(doc.doc_id)
            created = existing.created_at if existing else (doc.created_at or now)
            try:
                self._conn.execute("BEGIN")
                self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc.doc_id,))
                self._conn.execute(
                    "DELETE FROM documents WHERE source = ? AND doc_id != ?",
                    (doc.source, doc.doc_id),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc.doc_id,
                        doc.source,
                        doc.modality.value,
                        doc.content_hash,
                        doc.title,
                        json.dumps(doc.metadata, default=str),
                        created,
                        now,
                        len(chunks),
                    ),
                )
                self._conn.executemany(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            c.chunk_id,
                            doc.doc_id,
                            c.position,
                            c.modality.value,
                            c.source or doc.source,
                            c.content,
                            json.dumps(c.metadata, default=str),
                            None
                            if c.embedding is None
                            else np.asarray(c.embedding, dtype=np.float32).tobytes(),
                        )
                        for c in chunks
                    ],
                )
                if dims and current_dim is None:
                    self._set_meta("dimension", str(next(iter(dims))))
                self._bump()
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            doc.created_at, doc.updated_at, doc.chunk_count = created, now, len(chunks)

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            cur = self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            deleted = cur.rowcount > 0
            if deleted:
                self._bump()
            self._conn.execute("COMMIT")
            return deleted

    def update_embeddings(self, vectors: dict[str, np.ndarray], dimension: int) -> None:
        """Replace embeddings (used when rebuilding with a different embedder)."""
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.executemany(
                "UPDATE chunks SET embedding = ? WHERE chunk_id = ?",
                [(np.asarray(v, dtype=np.float32).tobytes(), cid) for cid, v in vectors.items()],
            )
            self._set_meta("dimension", str(dimension))
            self._bump()
            self._conn.execute("COMMIT")

    # ---------------------------------------------------------------- chunks
    _CHUNK_COLS = "chunk_id, doc_id, position, modality, source, content, metadata"

    @staticmethod
    def _row_to_chunk(row: tuple, embedding: bytes | None = None) -> Chunk:
        return Chunk(
            chunk_id=row[0],
            doc_id=row[1],
            position=row[2],
            modality=Modality(row[3]),
            source=row[4],
            content=row[5],
            metadata=json.loads(row[6] or "{}"),
            embedding=None if embedding is None else np.frombuffer(embedding, dtype=np.float32),
        )

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._CHUNK_COLS} FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return self._row_to_chunk(row) if row else None

    def get_document_chunks(self, doc_id: str) -> list[Chunk]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._CHUNK_COLS} FROM chunks WHERE doc_id = ? ORDER BY position",
                (doc_id,),
            ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def neighbors(self, chunk: Chunk, window: int = 1) -> tuple[list[Chunk], list[Chunk]]:
        """Chunks immediately before/after ``chunk`` in the same document."""
        if window <= 0:
            return [], []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._CHUNK_COLS} FROM chunks WHERE doc_id = ? AND position BETWEEN ? AND ? "
                "AND chunk_id != ? ORDER BY position",
                (chunk.doc_id, chunk.position - window, chunk.position + window, chunk.chunk_id),
            ).fetchall()
        found = [self._row_to_chunk(r) for r in rows]
        return (
            [c for c in found if c.position < chunk.position],
            [c for c in found if c.position > chunk.position],
        )

    def iter_chunks(self, with_embeddings: bool = False) -> Iterator[Chunk]:
        cols = self._CHUNK_COLS + (", embedding" if with_embeddings else "")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {cols} FROM chunks ORDER BY doc_id, position"
            ).fetchall()
        for row in rows:
            yield self._row_to_chunk(row[:7], row[7] if with_embeddings else None)

    def count_chunks(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    # ---------------------------------------------------------------- search
    def _load_matrix(self) -> _Matrix:
        rev = self.revision
        if self._matrix is not None and self._matrix.revision == rev:
            return self._matrix
        chunks: list[Chunk] = []
        vectors: list[np.ndarray] = []
        for chunk in self.iter_chunks(with_embeddings=True):
            if chunk.embedding is None:
                continue
            vectors.append(chunk.embedding)
            chunk.embedding = None
            chunks.append(chunk)
        dim = self.dimension or (vectors[0].shape[0] if vectors else 0)
        matrix = np.stack(vectors) if vectors else np.zeros((0, dim), dtype=np.float32)
        self._matrix = _Matrix(rev, chunks, matrix, {c.chunk_id: i for i, c in enumerate(chunks)})
        return self._matrix

    def all_chunks(self) -> list[Chunk]:
        """All chunks (without embeddings), cached until the store changes."""
        with self._lock:
            return list(self._load_matrix().chunks)

    def embedding_of(self, chunk_id: str) -> np.ndarray | None:
        with self._lock:
            m = self._load_matrix()
            i = m.index.get(chunk_id)
            return None if i is None else m.matrix[i]

    def search(
        self, query_vector: np.ndarray, k: int = 10, filters: SearchFilters | None = None
    ) -> list[ScoredChunk]:
        """Exact cosine-similarity search with metadata pre-filtering."""
        with self._lock:
            m = self._load_matrix()
        if m.matrix.shape[0] == 0 or k <= 0:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        if q.shape[0] != m.matrix.shape[1]:
            raise ValueError(f"query dimension {q.shape[0]} != store dimension {m.matrix.shape[1]}")
        scores = m.matrix @ q
        if filters is not None and not filters.is_empty():
            mask = np.array([filters.matches(c) for c in m.chunks], dtype=bool)
            scores = np.where(mask, scores, -np.inf)
        n_valid = int(np.isfinite(scores).sum())
        k = min(k, n_valid)
        if k == 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top], kind="stable")]
        return [
            ScoredChunk(m.chunks[i], float(scores[i]), {"dense_score": float(scores[i])})
            for i in top
        ]

    # ----------------------------------------------------------------- stats
    def stats(self) -> StoreStats:
        with self._lock:
            docs = int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            chunks = self.count_chunks()
            by_mod = dict(
                self._conn.execute("SELECT modality, COUNT(*) FROM chunks GROUP BY modality")
            )
            docs_by_mod = dict(
                self._conn.execute("SELECT modality, COUNT(*) FROM documents GROUP BY modality")
            )
            avg = self._conn.execute("SELECT AVG(LENGTH(content)) FROM chunks").fetchone()[0]
            updated = self._get_meta("updated_at")
        size = sum(
            p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file()
        )
        return StoreStats(
            documents=docs,
            chunks=chunks,
            by_modality=by_mod,
            documents_by_modality=docs_by_mod,
            dimension=self.dimension,
            storage_bytes=size,
            avg_chunk_chars=round(float(avg or 0), 1),
            last_updated=updated,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> LocalStore:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
