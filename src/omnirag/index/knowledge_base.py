"""A named knowledge base: its own store, embedding cache and configuration."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from omnirag.config import Settings
from omnirag.embed import CachedEmbedder, Embedder, EmbeddingCache, create_embedder, normalize_spec
from omnirag.generate import Answer, AnswerGenerator, create_llm
from omnirag.generate.llm import LLM
from omnirag.ingest import IngestContext, IngestError, IngestionPipeline
from omnirag.query.rewriter import QueryRewriter
from omnirag.retrieve import HybridRetriever, RetrievalResult
from omnirag.retrieve.context import CONTEXT_VERSION, index_text
from omnirag.store import Chunk, Document, LocalStore, SearchFilters
from omnirag.store.local import utcnow
from omnirag.textutil import TEXT_VERSION

# Bump when ingestion output changes in a way that should invalidate old chunks.
INGEST_VERSION = "2"
# Version of everything the stored vectors depend on: tokenisation and the
# contextual header chunks are indexed with.
INDEX_VERSION = TEXT_VERSION * 100 + CONTEXT_VERSION

ProgressFn = Callable[[str, Path, str], None]


@dataclass
class KBConfig:
    name: str
    description: str = ""
    embedder: str = "hashing:2048"
    chunk_size: int = 1200
    chunk_overlap: int = 150
    created_at: str = ""
    version: int = 1
    # Tokeniser/stemmer version the stored vectors were built with (see textutil).
    text_version: int = 1

    @classmethod
    def load(cls, path: Path) -> KBConfig:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


LLM_BACKENDS = ("", "none", "ollama", "openai")


@dataclass
class KBPreferences:
    """Per-knowledge-base answer settings, editable from the web UI.

    ``llm`` is ``""`` (use the server default, ``OMNIRAG_LLM``), ``none``
    (offline extractive answers), ``ollama`` or ``openai`` (any
    OpenAI-compatible endpoint). Empty ``model``/``base_url`` fall back to the
    environment configuration. API keys are never stored here.
    """

    llm: str = ""
    model: str = ""
    base_url: str = ""
    top_k: int = 5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KBPreferences:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        prefs = cls(**known)
        prefs.validate()
        return prefs

    def validate(self) -> None:
        self.llm = (self.llm or "").strip().lower()
        if self.llm == "openai-compatible":
            self.llm = "openai"
        if self.llm not in LLM_BACKENDS:
            raise ValueError(f"unknown LLM backend {self.llm!r} (use none, ollama or openai)")
        self.model = (self.model or "").strip()
        self.base_url = (self.base_url or "").strip().rstrip("/")
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base URL must start with http:// or https://")
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int):
            raise ValueError("top_k must be an integer between 1 and 50")
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be an integer between 1 and 50")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    chunks: int = 0
    seconds: float = 0.0

    @property
    def processed(self) -> int:
        return len(self.added) + len(self.updated)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["processed"] = self.processed
        return data


@dataclass
class KBStats:
    name: str
    description: str
    embedder: str
    documents: int
    chunks: int
    by_modality: dict[str, int]
    documents_by_modality: dict[str, int]
    dimension: int | None
    storage_bytes: int
    avg_chunk_chars: float
    created_at: str
    last_updated: str | None
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def doc_id_for(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def content_hash(path: Path, config: KBConfig) -> str:
    h = hashlib.sha256()
    h.update(f"v{INGEST_VERSION}|{config.chunk_size}|{config.chunk_overlap}|".encode())
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    # Sidecar captions/transcripts change the description of media files.
    for sidecar in _sidecar_candidates(path):
        if sidecar.is_file():
            h.update(sidecar.name.encode())
            h.update(sidecar.read_bytes())
    return h.hexdigest()


def _sidecar_candidates(path: Path) -> list[Path]:
    from omnirag.ingest.audio import TRANSCRIPT_SIDECAR_EXTENSIONS
    from omnirag.ingest.detector import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS
    from omnirag.ingest.image import image_sidecars

    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return image_sidecars(path)
    if ext in AUDIO_EXTENSIONS:
        return [path.with_suffix(e) for e in TRANSCRIPT_SIDECAR_EXTENSIONS]
    return []


class KnowledgeBase:
    """Ingest files into, search and query one knowledge base."""

    def __init__(self, path: str | Path, settings: Settings | None = None) -> None:
        self.path = Path(path)
        self.settings = settings or Settings.from_env()
        config_path = self.path / "kb.json"
        if not config_path.is_file():
            raise FileNotFoundError(f"no knowledge base at {self.path}")
        self.config = KBConfig.load(config_path)
        self.store = LocalStore(self.path / "store.sqlite")
        if self.config.text_version != INDEX_VERSION and not self.store.count_chunks():
            self._mark_text_version()
        self._cache: EmbeddingCache | None = None
        self._embedder: Embedder | None = None
        self._retriever: HybridRetriever | None = None

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def uploads_dir(self) -> Path:
        """Where files uploaded through the HTTP API are stored."""
        return self.path / "uploads"

    # ------------------------------------------------------------ preferences
    @property
    def preferences_path(self) -> Path:
        return self.path / "settings.json"

    @property
    def preferences(self) -> KBPreferences:
        try:
            data = json.loads(self.preferences_path.read_text(encoding="utf-8"))
            return KBPreferences.from_dict(data)
        except (OSError, ValueError, TypeError):
            return KBPreferences()

    def save_preferences(self, prefs: KBPreferences) -> KBPreferences:
        prefs.validate()
        self.preferences_path.write_text(
            json.dumps(prefs.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return prefs

    def llm_settings(self) -> tuple[str, Settings]:
        """The LLM spec and settings implied by this KB's preferences."""
        prefs = self.preferences
        if not prefs.llm:
            return self.settings.llm, self.settings
        if prefs.llm == "none":
            return "none", self.settings
        spec = prefs.llm + (f":{prefs.model}" if prefs.model else "")
        settings = self.settings
        if prefs.base_url and prefs.llm == "ollama":
            settings = settings.with_overrides(ollama_host=prefs.base_url)
        elif prefs.base_url and prefs.llm == "openai":
            settings = settings.with_overrides(openai_base_url=prefs.base_url)
        return spec, settings

    def default_llm(self) -> LLM | None:
        """The LLM selected by this KB's preferences (``None`` = extractive)."""
        spec, settings = self.llm_settings()
        return create_llm(spec, settings)

    # ---------------------------------------------------------- maintenance
    def _mark_text_version(self) -> None:
        self.config.text_version = INDEX_VERSION
        self.config.save(self.path / "kb.json")

    def ensure_current(self) -> bool:
        """Re-embed stored chunks built with an older index format.

        The stored vectors depend on OmniRAG's tokenisation (hashing embedder)
        and on the contextual header every chunk is embedded with (all
        embedders), so a knowledge base from an older version is re-embedded
        once. Returns True when a rebuild happened.
        """
        if self.config.text_version == INDEX_VERSION:
            return False
        rebuilt = False
        if self.store.count_chunks():
            self.rebuild()
            rebuilt = True
        self._mark_text_version()
        return rebuilt

    # ------------------------------------------------------------ components
    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            if self._cache is None:
                self._cache = EmbeddingCache(self.path / "embed_cache.sqlite")
            inner = create_embedder(self.config.embedder, self.settings)
            self._embedder = CachedEmbedder(inner, self._cache)
        return self._embedder

    def retriever(self, llm: LLM | None = None) -> HybridRetriever:
        self.ensure_current()
        if self._retriever is None:
            self._retriever = HybridRetriever(self.store, self.embedder)
        self._retriever.rewriter = QueryRewriter(llm)
        return self._retriever

    # ------------------------------------------------------------- ingestion
    def ingest(
        self,
        paths: Iterable[str | Path],
        recursive: bool = True,
        force: bool = False,
        progress: ProgressFn | None = None,
        root: str | Path | None = None,
    ) -> IngestReport:
        """Ingest files/directories. Unchanged files (same content hash) are skipped.

        ``root`` sets the base directory for the short display paths stored with
        each chunk (by default the ingested directory or the files' common parent).
        """
        started = time.perf_counter()
        self.ensure_current()
        report = IngestReport()
        ctx = IngestContext(
            settings=self.settings,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            root=Path(root) if root is not None else None,
        )
        pipeline = IngestionPipeline(ctx)
        files = pipeline.prepare(paths, recursive=recursive)
        for path in files:
            source = str(path)
            try:
                digest = content_hash(path, self.config)
                existing = self.store.get_document_by_source(source)
                if existing and existing.content_hash == digest and not force:
                    report.unchanged.append(source)
                    if progress:
                        progress("unchanged", path, "")
                    continue
                parsed = pipeline.parse(path)
                if parsed.warnings:
                    report.warnings[source] = parsed.warnings
                n = self._store_parsed(parsed, source, digest, ctx)
                report.chunks += n
                (report.updated if existing else report.added).append(source)
                if progress:
                    progress("updated" if existing else "added", path, f"{n} chunks")
            except (IngestError, OSError, UnicodeDecodeError, ValueError) as exc:
                report.failed[source] = str(exc)
                if progress:
                    progress("failed", path, str(exc))
        report.seconds = round(time.perf_counter() - started, 3)
        return report

    def _store_parsed(self, parsed, source: str, digest: str, ctx: IngestContext) -> int:
        doc_id = doc_id_for(source)
        rel = ctx.display_path(parsed.path)
        chunks: list[Chunk] = []
        for pos, raw in enumerate(parsed.chunks):
            meta = dict(raw.metadata)
            meta.setdefault("title", parsed.title)
            meta["path"] = rel
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}-{pos:04d}",
                    doc_id=doc_id,
                    content=raw.content,
                    modality=parsed.modality,
                    source=source,
                    position=pos,
                    metadata=meta,
                )
            )
        if chunks:
            vectors = self.embedder.embed_documents(
                [index_text(c.content, c.metadata) for c in chunks]
            )
            for chunk, vec in zip(chunks, vectors, strict=True):
                chunk.embedding = vec
        doc = Document(
            doc_id=doc_id,
            source=source,
            modality=parsed.modality,
            content_hash=digest,
            title=parsed.title,
            metadata={**parsed.metadata, "path": rel, "warnings": parsed.warnings},
        )
        self.store.upsert_document(doc, chunks)
        return len(chunks)

    def remove(self, source: str | Path) -> bool:
        """Remove a document by source path (or doc id)."""
        src = str(Path(source).expanduser().resolve()) if Path(source).exists() else str(source)
        doc = self.store.get_document_by_source(src) or self.store.get_document(str(source))
        if doc is None:
            return False
        return self.store.delete_document(doc.doc_id)

    def prune(self) -> list[str]:
        """Remove documents whose source files no longer exist."""
        removed = []
        for doc in self.store.list_documents():
            if not Path(doc.source).exists():
                self.store.delete_document(doc.doc_id)
                removed.append(doc.source)
        return removed

    def rebuild(self, embedder: str | None = None, progress: ProgressFn | None = None) -> int:
        """Re-embed every chunk (e.g. after switching embedders). Returns chunk count."""
        if embedder:
            self.config.embedder = normalize_spec(embedder)
            self.config.save(self.path / "kb.json")
            self._embedder = None
            self._retriever = None
        chunks = list(self.store.iter_chunks())
        if not chunks:
            return 0
        vectors: dict = {}
        batch = 256
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            embedded = self.embedder.embed_documents(
                [index_text(c.content, c.metadata) for c in part]
            )
            for c, v in zip(part, embedded, strict=True):
                vectors[c.chunk_id] = v
        dim = int(next(iter(vectors.values())).shape[0])
        self.store.update_embeddings(vectors, dim)
        return len(chunks)

    # ----------------------------------------------------------------- query
    def search(
        self,
        query: str,
        k: int = 5,
        filters: SearchFilters | None = None,
        mode: str = "hybrid",
        neighbors: int = 1,
    ) -> RetrievalResult:
        return self.retriever().retrieve(
            query, k=k, filters=filters, mode=mode, neighbors=neighbors
        )

    def _resolve_llm(self, llm: str | LLM | None) -> LLM | None:
        if isinstance(llm, LLM) or llm is None:
            return llm
        return create_llm(llm, self.settings)

    def ask(
        self,
        question: str,
        llm: str | LLM | None = "none",
        k: int = 5,
        filters: SearchFilters | None = None,
        mode: str = "hybrid",
        neighbors: int = 1,
        hyde: bool = False,
    ) -> Answer:
        """Retrieve relevant chunks and answer with citations."""
        started = time.perf_counter()
        model = self._resolve_llm(llm)
        retrieved = self.retriever(model).retrieve(
            question, k=k, filters=filters, mode=mode, neighbors=neighbors, use_hyde=hyde
        )
        retrieve_ms = (time.perf_counter() - started) * 1000
        answer = AnswerGenerator(model).generate(
            retrieved.query.text or question, retrieved.results
        )
        _finish_answer(answer, question, retrieved, mode, started, retrieve_ms)
        return answer

    def ask_stream(
        self,
        question: str,
        llm: str | LLM | None = "none",
        k: int = 5,
        filters: SearchFilters | None = None,
        mode: str = "hybrid",
        neighbors: int = 1,
        hyde: bool = False,
    ) -> Iterator[tuple[str, Any]]:
        """Like :meth:`ask`, but yields events while the answer is produced.

        Events: ``("sources", {"sources": [...], "query": {...}, "retrieve_ms": ...})``,
        then ``("delta", str)`` pieces of text, then ``("answer", Answer)``.
        """
        started = time.perf_counter()
        model = self._resolve_llm(llm)
        retrieved = self.retriever(model).retrieve(
            question, k=k, filters=filters, mode=mode, neighbors=neighbors, use_hyde=hyde
        )
        retrieve_ms = (time.perf_counter() - started) * 1000
        generator = AnswerGenerator(model)
        for event, payload in generator.stream(retrieved.query.text or question, retrieved.results):
            if event == "sources":
                yield (
                    "sources",
                    {
                        "sources": [src.to_dict() for src in payload],
                        "query": _query_info(retrieved, mode),
                        "retrieve_ms": round(retrieve_ms, 1),
                    },
                )
            elif event == "answer":
                _finish_answer(payload, question, retrieved, mode, started, retrieve_ms)
                yield "answer", payload
            else:
                yield event, payload

    # ----------------------------------------------------------------- stats
    def stats(self) -> KBStats:
        s = self.store.stats()
        cache_bytes = sum(
            p.stat().st_size for p in self.path.glob("embed_cache.sqlite*") if p.is_file()
        )
        return KBStats(
            name=self.config.name,
            description=self.config.description,
            embedder=self.config.embedder,
            documents=s.documents,
            chunks=s.chunks,
            by_modality=s.by_modality,
            documents_by_modality=s.documents_by_modality,
            dimension=s.dimension,
            storage_bytes=s.storage_bytes + cache_bytes,
            avg_chunk_chars=s.avg_chunk_chars,
            created_at=self.config.created_at,
            last_updated=s.last_updated,
            path=str(self.path),
        )

    def documents(self) -> list[Document]:
        return self.store.list_documents()

    def close(self) -> None:
        self.store.close()
        if self._cache is not None:
            self._cache.close()

    def __enter__(self) -> KnowledgeBase:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _query_info(retrieved: RetrievalResult, mode: str) -> dict[str, Any]:
    parsed = retrieved.query
    filters = retrieved.plan.filters
    return {
        "text": parsed.text,
        "intent": parsed.intent.value,
        "modality_hints": [m.value for m in parsed.modality_hints],
        "filters": {
            "modalities": [m.value for m in (filters.modalities or [])],
            "exclude_modalities": [m.value for m in (filters.exclude_modalities or [])],
            "sources": filters.sources or [],
            "doc_ids": filters.doc_ids or [],
            "metadata": filters.metadata,
        },
        "mode": mode,
    }


def _finish_answer(
    answer: Answer,
    question: str,
    retrieved: RetrievalResult,
    mode: str,
    started: float,
    retrieve_ms: float,
) -> None:
    answer.question = question
    answer.timings["retrieve_ms"] = round(retrieve_ms, 1)
    answer.timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    answer.query = _query_info(retrieved, mode)


def new_config(name: str, description: str, embedder: str, settings: Settings) -> KBConfig:
    return KBConfig(
        name=name,
        description=description,
        embedder=normalize_spec(embedder),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        created_at=utcnow(),
        text_version=INDEX_VERSION,
    )
