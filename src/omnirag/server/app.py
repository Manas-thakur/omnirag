"""FastAPI server: JSON API, an SSE answer stream and a no-build web UI.

Security model: meant for local or trusted-network use. Set ``OMNIRAG_API_KEY``
to require a key on every ``/api/*`` route (except ``/api/health``), and
``OMNIRAG_CORS_ORIGINS`` to allow browser clients from other origins. The
``/api/ingest`` endpoint reads paths on the server's filesystem; uploads are
stored inside the knowledge base directory.
"""

from __future__ import annotations

import html
import json
import mimetypes
import os
import re
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from omnirag import __version__
from omnirag.config import Settings
from omnirag.generate.llm import LLM, LLMError, create_llm
from omnirag.health import probe_llm
from omnirag.index import IndexManager, KBPreferences, KnowledgeBase, KnowledgeBaseError
from omnirag.ingest.detector import (
    AUDIO_EXTENSIONS,
    CODE_LANGUAGES,
    IMAGE_EXTENSIONS,
    TABLE_EXTENSIONS,
    TEXT_EXTENSIONS,
    TRANSCRIPT_EXTENSIONS,
)
from omnirag.server.related import related_questions
from omnirag.server.security import (
    API_KEY_HEADER,
    APIKeyMiddleware,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from omnirag.store.models import Document, Modality, SearchFilters

STATIC_DIR = Path(__file__).parent / "static"

#: File types accepted by the upload endpoint (everything the ingestors handle).
UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
    TEXT_EXTENSIONS
    | IMAGE_EXTENSIONS
    | AUDIO_EXTENSIONS
    | TRANSCRIPT_EXTENSIONS
    | TABLE_EXTENSIONS
    | set(CODE_LANGUAGES)
)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_UNSAFE_NAME = re.compile(r"[^\w.\- ]+")
_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(10)),
    *(f"lpt{i}" for i in range(10)),
}

# The page loads only same-origin scripts; fonts may come from Google Fonts.
PAGE_CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
# Raw source files (SVG can carry script) are rendered inert.
RAW_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    kb: str | None = None
    top_k: int | None = Field(None, ge=1, le=50)
    llm: str | None = None
    modalities: list[str] | None = None
    sources: list[str] | None = None
    #: Restrict retrieval to these documents (a "scoped" chat).
    doc_ids: list[str] | None = Field(None, max_length=1000)
    mode: str = "hybrid"
    neighbors: int = Field(1, ge=0, le=3)


class RelatedRequest(BaseModel):
    query: str = Field("", max_length=4000)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    doc_ids: list[str] | None = Field(None, max_length=1000)
    limit: int = Field(4, ge=1, le=10)


class IngestRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    kb: str | None = None
    recursive: bool = True
    force: bool = False


class CreateKBRequest(BaseModel):
    name: str
    description: str = ""
    embedder: str | None = None


class PreferencesRequest(BaseModel):
    llm: str = ""
    model: str = ""
    base_url: str = ""
    top_k: int = Field(5, ge=1, le=50)


class _StaticFiles(StaticFiles):
    """Static assets, revalidated on every load (cheap 304s) so upgrades show up."""

    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def safe_filename(name: str) -> str:
    """Reduce an uploaded file name to a safe basename (no directories)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_NAME.sub("_", base).strip(" .")
    if base.split(".", 1)[0].lower() in _RESERVED_NAMES:
        base = "_" + base
    if len(base) > 150:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 150 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else base[:150]
    return base


def create_app(
    home: str | Path | None = None,
    default_kb: str = "default",
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = IndexManager(home, settings)
    kbs: dict[str, KnowledgeBase] = {}
    lock = threading.RLock()
    max_upload_bytes = int(settings.max_upload_mb * 1024 * 1024)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        with lock:
            for kb in kbs.values():
                kb.close()
            kbs.clear()

    app = FastAPI(
        title="OmniRAG",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Middleware: the last one added is the outermost.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=max_upload_bytes + 64 * 1024,  # multipart framing overhead
        suffixes=("/upload",),
    )
    if settings.api_key:
        app.add_middleware(
            APIKeyMiddleware, api_key=settings.api_key, public={"/api/health", "/api/docs"}
        )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", API_KEY_HEADER],
            allow_credentials=False,
        )
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", _StaticFiles(directory=STATIC_DIR), name="static")

    # ---------------------------------------------------------------- helpers
    def get_kb(name: str | None) -> KnowledgeBase:
        name = name or default_kb
        with lock:
            if name not in kbs:
                try:
                    kbs[name] = manager.get(name)
                except KnowledgeBaseError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
            return kbs[name]

    def get_doc(kb: KnowledgeBase, doc_id: str) -> Document:
        doc = kb.store.get_document(doc_id) if _ID_RE.match(doc_id) else None
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        return doc

    def is_upload(kb: KnowledgeBase, source: str) -> bool:
        try:
            return Path(source).resolve().is_relative_to(kb.uploads_dir.resolve())
        except (OSError, ValueError):
            return False

    def doc_dict(kb: KnowledgeBase, d: Document) -> dict[str, Any]:
        path = Path(d.source)
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        return {
            "doc_id": d.doc_id,
            "source": d.source,
            "path": d.metadata.get("path", d.source),
            "name": path.name,
            "title": d.title,
            "modality": d.modality.value,
            "chunks": d.chunk_count,
            "size_bytes": size,
            "missing": size is None,
            "uploaded": is_upload(kb, d.source),
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "warnings": d.metadata.get("warnings") or [],
        }

    def kb_summary(kb: KnowledgeBase) -> dict[str, Any]:
        s = kb.store.stats()
        return {
            "name": kb.name,
            "description": kb.config.description,
            "embedder": kb.config.embedder,
            "documents": s.documents,
            "chunks": s.chunks,
            "created_at": kb.config.created_at,
            "is_default": kb.name == default_kb,
        }

    def resolve_llm(kb: KnowledgeBase, spec: str | None) -> LLM | None:
        try:
            if spec:
                return create_llm(spec, kb.settings)
            return kb.default_llm()
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def build_filters(req: QueryRequest) -> SearchFilters | None:
        filters = SearchFilters()
        try:
            if req.modalities:
                filters.modalities = [Modality.parse(m) for m in req.modalities]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if req.sources:
            filters.sources = req.sources
        if req.doc_ids:
            filters.doc_ids = check_ids(req.doc_ids, "doc_ids")
        return None if filters.is_empty() else filters

    def check_ids(ids: list[str], field: str) -> list[str]:
        bad = [i for i in ids if not _ID_RE.match(i)]
        if bad:
            raise HTTPException(status_code=400, detail=f"invalid {field}: {bad[0][:80]!r}")
        return list(dict.fromkeys(ids))

    # ------------------------------------------------------------------- page
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        page = page.replace("__DEFAULT_KB__", html.escape(default_kb, quote=True))
        page = page.replace("__VERSION__", html.escape(__version__))
        return HTMLResponse(
            page, headers={"Content-Security-Policy": PAGE_CSP, "Cache-Control": "no-cache"}
        )

    # ----------------------------------------------------------------- status
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "default_kb": default_kb,
            "llm": settings.llm,
            "auth_required": bool(settings.api_key),
        }

    @app.get("/api/status")
    def status(kb: str | None = None, probe: bool = True) -> dict[str, Any]:
        """Embedder in use, configured LLM backend and whether it is reachable."""
        out: dict[str, Any] = {
            "version": __version__,
            "auth_required": bool(settings.api_key),
            "default_kb": default_kb,
            "max_upload_mb": settings.max_upload_mb,
            "upload_extensions": sorted(UPLOAD_EXTENSIONS),
            "kb": None,
            "embedder": None,
            "defaults": {
                "llm": settings.llm,
                "ollama": {"model": settings.ollama_model, "base_url": settings.ollama_url},
                "openai": {"model": settings.openai_model, "base_url": settings.openai_base_url},
            },
        }
        name = kb or default_kb
        if manager.exists(name):
            knowledge_base = get_kb(name)
            spec, llm_settings = knowledge_base.llm_settings()
            dim = knowledge_base.store.dimension
            out["kb"] = name
            out["embedder"] = {
                "spec": knowledge_base.config.embedder,
                "dimension": dim,
                "offline": knowledge_base.config.embedder.startswith("hashing"),
            }
            prefs = knowledge_base.preferences
        else:
            spec, llm_settings, prefs = settings.llm, settings, KBPreferences()
        kind, _, model = (spec or "none").partition(":")
        kind = kind.lower() or "none"
        if kind == "ollama":
            model, base_url = model or llm_settings.ollama_model, llm_settings.ollama_url
        elif kind in {"openai", "openai-compatible"}:
            kind = "openai"
            model, base_url = model or llm_settings.openai_model, llm_settings.openai_base_url
        else:
            kind, model, base_url = "none", "", ""
        result = probe_llm(spec, llm_settings) if probe and kind != "none" else None
        out["llm"] = {
            "backend": kind,
            "model": model,
            "base_url": base_url,
            "source": "kb" if prefs.llm else "server",
            "reachable": None if result is None else result.reachable,
            "detail": "offline extractive answers"
            if kind == "none"
            else (result.detail if result else ""),
            "latency_ms": result.latency_ms if result else None,
            "models": result.models[:50] if result else [],
        }
        return out

    # ------------------------------------------------------- knowledge bases
    @app.get("/api/kbs")
    def list_kbs() -> list[dict[str, Any]]:
        return [kb_summary(get_kb(cfg.name)) for cfg in manager.list()]

    @app.post("/api/kbs", status_code=201)
    def create_kb(req: CreateKBRequest) -> dict[str, Any]:
        try:
            kb = manager.create(req.name.strip(), req.description.strip(), req.embedder)
        except (KnowledgeBaseError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with lock:
            kbs[kb.name] = kb
        return kb_summary(kb)

    @app.get("/api/kbs/{name}")
    def get_kb_info(name: str) -> dict[str, Any]:
        return kb_summary(get_kb(name))

    @app.delete("/api/kbs/{name}")
    def delete_kb(name: str) -> dict[str, Any]:
        kb = get_kb(name)
        with lock:
            kbs.pop(name, None)
            kb.close()
            try:
                manager.delete(name)
            except (KnowledgeBaseError, OSError) as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"deleted": name}

    @app.get("/api/kbs/{name}/settings")
    def get_settings(name: str) -> dict[str, Any]:
        return get_kb(name).preferences.to_dict()

    @app.put("/api/kbs/{name}/settings")
    def put_settings(name: str, req: PreferencesRequest) -> dict[str, Any]:
        kb = get_kb(name)
        try:
            prefs = KBPreferences.from_dict(req.model_dump())
            return kb.save_preferences(prefs).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/kbs/{name}/stats")
    def kb_stats(name: str) -> dict[str, Any]:
        return get_kb(name).stats().to_dict()

    @app.get("/api/stats")
    def stats(kb: str | None = None) -> dict[str, Any]:
        return get_kb(kb).stats().to_dict()

    # ------------------------------------------------------------- documents
    @app.get("/api/kbs/{name}/documents")
    def kb_documents(name: str) -> list[dict[str, Any]]:
        kb = get_kb(name)
        return [doc_dict(kb, d) for d in kb.documents()]

    @app.delete("/api/kbs/{name}/documents/{doc_id}")
    def delete_document(name: str, doc_id: str) -> dict[str, Any]:
        kb = get_kb(name)
        doc = get_doc(kb, doc_id)
        kb.store.delete_document(doc.doc_id)
        removed_file = False
        if is_upload(kb, doc.source):
            with suppress(OSError):
                Path(doc.source).unlink()
                removed_file = True
        return {"deleted": doc.doc_id, "removed_file": removed_file}

    @app.post("/api/kbs/{name}/documents/{doc_id}/reingest")
    def reingest_document(name: str, doc_id: str) -> dict[str, Any]:
        kb = get_kb(name)
        doc = get_doc(kb, doc_id)
        source = Path(doc.source)
        if not source.is_file():
            raise HTTPException(status_code=410, detail="the source file no longer exists")
        rel = str(doc.metadata.get("path") or source.name)
        posix = source.as_posix()
        root = Path(posix[: -len(rel)]) if rel and posix.endswith("/" + rel) else source.parent
        report = kb.ingest([source], force=True, root=root)
        return {"document": doc_dict(kb, get_doc(kb, doc_id)), "report": report.to_dict()}

    @app.post("/api/kbs/{name}/upload")
    def upload(name: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        """Store uploaded files under the KB directory and ingest them."""
        kb = get_kb(name)
        kb.uploads_dir.mkdir(parents=True, exist_ok=True)
        saved: list[tuple[str, Path, int]] = []
        names = [safe_filename(f.filename or "") for f in files]
        for upload_file, filename in zip(files, names, strict=True):
            if not filename or Path(filename).suffix.lower() not in UPLOAD_EXTENSIONS:
                raise HTTPException(
                    status_code=415,
                    detail=f"unsupported file type: {upload_file.filename or '(unnamed)'}",
                )
        try:
            for upload_file, filename in zip(files, names, strict=True):
                target = kb.uploads_dir / filename
                partial = target.with_name(target.name + ".part")
                size = 0
                with partial.open("wb") as out:
                    while block := upload_file.file.read(1 << 20):
                        size += len(block)
                        if size > max_upload_bytes:
                            out.close()
                            partial.unlink(missing_ok=True)
                            raise HTTPException(
                                status_code=413,
                                detail=f"{filename} exceeds the {settings.max_upload_mb:g} MB limit",
                            )
                        out.write(block)
                os.replace(partial, target)
                saved.append((filename, target, size))
        finally:
            for upload_file in files:
                upload_file.file.close()
        report = kb.ingest([p for _, p, _ in saved], root=kb.uploads_dir)
        status_by_source = {
            **dict.fromkeys(report.added, "added"),
            **dict.fromkeys(report.updated, "updated"),
            **dict.fromkeys(report.unchanged, "unchanged"),
            **dict.fromkeys(report.failed, "failed"),
        }
        out_files = []
        for filename, path, size in saved:
            source = str(path.resolve())
            doc = kb.store.get_document_by_source(source)
            out_files.append(
                {
                    "name": filename,
                    "size_bytes": size,
                    "status": status_by_source.get(source, "skipped"),
                    "error": report.failed.get(source),
                    "doc_id": doc.doc_id if doc else None,
                    "chunks": doc.chunk_count if doc else 0,
                    "warnings": report.warnings.get(source, []),
                }
            )
        return {"files": out_files, "report": report.to_dict()}

    @app.post("/api/ingest")
    def ingest(req: IngestRequest) -> dict[str, Any]:
        name = req.kb or default_kb
        try:
            if not manager.exists(name):
                manager.create(name).close()
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        kb = get_kb(name)
        try:
            report = kb.ingest(req.paths, recursive=req.recursive, force=req.force)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report.to_dict()

    # ----------------------------------------------------------------- query
    @app.post("/api/query")
    def query(req: QueryRequest) -> dict[str, Any]:
        kb = get_kb(req.kb)
        filters = build_filters(req)
        model = resolve_llm(kb, req.llm)
        try:
            answer = kb.ask(
                req.query,
                llm=model,
                k=req.top_k or kb.preferences.top_k,
                filters=filters,
                mode=req.mode,
                neighbors=req.neighbors,
            )
        except (ValueError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return answer.to_dict()

    @app.post("/api/query/stream")
    def query_stream(req: QueryRequest) -> StreamingResponse:
        """Server-sent events: ``sources``, then ``delta`` pieces, then ``done``.

        ``error`` is sent instead of ``done`` if generation fails mid-stream.
        """
        kb = get_kb(req.kb)
        filters = build_filters(req)
        model = resolve_llm(kb, req.llm)
        if req.mode not in {"hybrid", "dense", "bm25"}:
            raise HTTPException(status_code=400, detail=f"unknown retrieval mode {req.mode!r}")
        k = req.top_k or kb.preferences.top_k

        def events() -> Iterator[str]:
            try:
                for event, payload in kb.ask_stream(
                    req.query,
                    llm=model,
                    k=k,
                    filters=filters,
                    mode=req.mode,
                    neighbors=req.neighbors,
                ):
                    if event == "delta":
                        yield _sse("delta", {"text": payload})
                    elif event == "sources":
                        yield _sse("sources", payload)
                    elif event == "answer":
                        yield _sse("done", payload.to_dict())
            except (ValueError, LLMError) as exc:
                yield _sse("error", {"detail": str(exc)})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/kbs/{name}/related")
    def related(name: str, req: RelatedRequest) -> dict[str, Any]:
        """Follow-up questions phrased offline from the sources' headings and symbols.

        With ``chunk_ids`` (the chunks an answer used) the questions point at
        nearby sections of the same documents; without them they are starter
        questions across the knowledge base. ``doc_ids`` keeps them in scope.
        """
        kb = get_kb(name)
        chunk_ids = check_ids(req.chunk_ids, "chunk_ids")
        doc_ids = check_ids(req.doc_ids, "doc_ids") if req.doc_ids else None
        nearby = []
        if req.query.strip() and chunk_ids:
            scope = SearchFilters(doc_ids=doc_ids) if doc_ids else None
            try:
                found = kb.search(req.query, k=req.limit * 3, filters=scope, neighbors=0)
                nearby = [r.chunk for r in found.results]
            except ValueError:
                nearby = []
        questions = related_questions(
            kb.store, req.query, chunk_ids, doc_ids, req.limit, nearby=nearby
        )
        return {"questions": questions}

    @app.get("/api/kbs/{name}/chunks/{chunk_id}")
    def chunk(name: str, chunk_id: str, window: int = 1) -> dict[str, Any]:
        kb = get_kb(name)
        c = kb.store.get_chunk(chunk_id) if _ID_RE.match(chunk_id) else None
        if c is None:
            raise HTTPException(status_code=404, detail="chunk not found")
        before, after = kb.store.neighbors(c, max(0, min(window, 3)))

        def as_dict(x):
            return {
                "chunk_id": x.chunk_id,
                "position": x.position,
                "content": x.content,
                "metadata": x.metadata,
            }

        return {
            **as_dict(c),
            "doc_id": c.doc_id,
            "source": c.source,
            "modality": c.modality.value,
            "before": [as_dict(x) for x in before],
            "after": [as_dict(x) for x in after],
        }

    @app.get("/api/kbs/{name}/documents/{doc_id}/raw", include_in_schema=False)
    def raw_document(name: str, doc_id: str) -> FileResponse:
        """Serve an ingested source file.

        Only files registered as documents in the KB are served (looked up by
        id, never by a client-supplied path), and active content is neutralised.
        """
        doc = get_doc(get_kb(name), doc_id)
        path = Path(doc.source)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="document not found")
        media_type = mimetypes.guess_type(path.name)[0] or "text/plain"
        if not media_type.startswith(("image/", "audio/")) and media_type not in {
            "application/pdf",
            "text/csv",
        }:
            media_type = "text/plain; charset=utf-8"
        return FileResponse(
            path,
            media_type=media_type,
            content_disposition_type="inline",
            filename=path.name,
            headers={"Content-Security-Policy": RAW_CSP},
        )

    return app


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
