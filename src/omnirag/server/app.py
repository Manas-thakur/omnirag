"""FastAPI server: JSON API plus a single-page, no-build web UI.

Intended for local / trusted-network use: the ingest endpoint reads paths on
the server's filesystem.
"""

from __future__ import annotations

import mimetypes
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from omnirag import __version__
from omnirag.config import Settings
from omnirag.generate.llm import LLMError
from omnirag.index import IndexManager, KnowledgeBase, KnowledgeBaseError
from omnirag.store.models import Modality, SearchFilters

STATIC_DIR = Path(__file__).parent / "static"


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    kb: str | None = None
    top_k: int = Field(5, ge=1, le=50)
    llm: str | None = None
    modalities: list[str] | None = None
    sources: list[str] | None = None
    mode: str = "hybrid"
    neighbors: int = Field(1, ge=0, le=3)


class IngestRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    kb: str | None = None
    recursive: bool = True
    force: bool = False


class CreateKBRequest(BaseModel):
    name: str
    description: str = ""
    embedder: str | None = None


def create_app(
    home: str | Path | None = None,
    default_kb: str = "default",
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = IndexManager(home, settings)
    kbs: dict[str, KnowledgeBase] = {}
    lock = threading.Lock()

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

    def get_kb(name: str | None) -> KnowledgeBase:
        name = name or default_kb
        with lock:
            if name not in kbs:
                try:
                    kbs[name] = manager.get(name)
                except KnowledgeBaseError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
            return kbs[name]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__DEFAULT_KB__", default_kb))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "default_kb": default_kb,
            "llm": settings.llm,
        }

    @app.get("/api/kbs")
    def list_kbs() -> list[dict[str, Any]]:
        out = []
        for cfg in manager.list():
            kb = get_kb(cfg.name)
            s = kb.store.stats()
            out.append(
                {
                    "name": cfg.name,
                    "description": cfg.description,
                    "embedder": cfg.embedder,
                    "documents": s.documents,
                    "chunks": s.chunks,
                }
            )
        return out

    @app.post("/api/kbs", status_code=201)
    def create_kb(req: CreateKBRequest) -> dict[str, Any]:
        try:
            kb = manager.create(req.name, req.description, req.embedder)
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with lock:
            kbs[req.name] = kb
        return {"name": kb.name, "embedder": kb.config.embedder}

    @app.get("/api/kbs/{name}/stats")
    def kb_stats(name: str) -> dict[str, Any]:
        return get_kb(name).stats().to_dict()

    @app.get("/api/kbs/{name}/documents")
    def kb_documents(name: str) -> list[dict[str, Any]]:
        return [
            {
                "doc_id": d.doc_id,
                "source": d.source,
                "path": d.metadata.get("path", d.source),
                "title": d.title,
                "modality": d.modality.value,
                "chunks": d.chunk_count,
                "updated_at": d.updated_at,
            }
            for d in get_kb(name).documents()
        ]

    @app.get("/api/stats")
    def stats(kb: str | None = None) -> dict[str, Any]:
        return get_kb(kb).stats().to_dict()

    @app.post("/api/query")
    def query(req: QueryRequest) -> dict[str, Any]:
        kb = get_kb(req.kb)
        filters = SearchFilters()
        try:
            if req.modalities:
                filters.modalities = [Modality.parse(m) for m in req.modalities]
            if req.sources:
                filters.sources = req.sources
            answer = kb.ask(
                req.query,
                llm=req.llm or settings.llm,
                k=req.top_k,
                filters=None if filters.is_empty() else filters,
                mode=req.mode,
                neighbors=req.neighbors,
            )
        except (ValueError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return answer.to_dict()

    @app.post("/api/ingest")
    def ingest(req: IngestRequest) -> dict[str, Any]:
        name = req.kb or default_kb
        if not manager.exists(name):
            manager.create(name).close()
        kb = get_kb(name)
        try:
            report = kb.ingest(req.paths, recursive=req.recursive, force=req.force)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report.to_dict()

    @app.get("/api/kbs/{name}/chunks/{chunk_id}")
    def chunk(name: str, chunk_id: str, window: int = 1) -> dict[str, Any]:
        kb = get_kb(name)
        c = kb.store.get_chunk(chunk_id)
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
        """Serve an ingested source file (only files registered in the KB)."""
        doc = get_kb(name).store.get_document(doc_id)
        if doc is None or not Path(doc.source).is_file():
            raise HTTPException(status_code=404, detail="document not found")
        media_type = mimetypes.guess_type(doc.source)[0] or "text/plain"
        if media_type in {"text/html", "application/javascript", "text/javascript"}:
            media_type = "text/plain"
        return FileResponse(doc.source, media_type=media_type)

    return app
