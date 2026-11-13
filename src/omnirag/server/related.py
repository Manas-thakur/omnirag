"""Offline follow-up questions built from the structure of the indexed sources.

No model is involved: questions are phrased from chunk metadata that ingestion
already records (Markdown/HTML section headings, code symbols, table titles,
transcript timestamps, image file names). Given the chunks an answer used, the
suggestions point at *neighbouring* material in the same documents that the
answer did not cover, so they read as natural next questions.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from omnirag.store.local import LocalStore
from omnirag.store.models import Chunk, Document, Modality


def _phrase(text: str) -> str:
    """Lower-case a heading for use mid-sentence, keeping acronyms ("HTTP 429")."""
    text = " ".join(text.split())
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        return text[0].lower() + text[1:]
    return text


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def question_for(chunk: Chunk, doc: Document | None) -> str | None:
    """Phrase one question about ``chunk``, or ``None`` if nothing fits."""
    meta = chunk.metadata
    name = Path(chunk.source).name
    title = _short(str(meta.get("title") or (doc.title if doc else "") or name))
    if chunk.modality == Modality.TEXT:
        section = str(meta.get("section") or "").strip()
        if section and section != title:
            return f"What does {title} say about {_phrase(_short(section))}?"
        return f"Summarise {title}"
    if chunk.modality == Modality.CODE:
        symbol = str(meta.get("symbol") or "").strip()
        kind = str(meta.get("kind") or "")
        if not symbol or kind == "module":
            return f"What does {name} do?"
        if kind in {"function", "method"}:
            return f"How does {symbol}() work?"
        if kind == "class":
            return f"How does the {symbol} class work?"
        return f"What is {symbol} in {name}?"
    if chunk.modality == Modality.TABLE:
        if meta.get("kind") == "summary":
            return f"What does {title} contain?"
        start, end = meta.get("row_start"), meta.get("row_end")
        if start and end:
            return f"What do rows {start}–{end} of {title} show?"
        return f"What does {title} contain?"
    if chunk.modality == Modality.AUDIO:
        stamp = str(meta.get("timestamp") or "").split("-")[0].strip()
        if stamp:
            return f"What was discussed around {stamp} in {title}?"
        return f"Summarise {title}"
    if chunk.modality == Modality.IMAGE:
        return f"What does {name} show?"
    return None


def _interleave_by_modality(docs: list[Document]) -> list[Document]:
    buckets: dict[Modality, list[Document]] = {}
    for d in docs:
        buckets.setdefault(d.modality, []).append(d)
    out: list[Document] = []
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket:
                out.append(bucket.pop(0))
    return out


def related_questions(
    store: LocalStore,
    query: str = "",
    chunk_ids: Iterable[str] = (),
    doc_ids: Iterable[str] | None = None,
    limit: int = 4,
    nearby: Iterable[Chunk] = (),
) -> list[dict[str, Any]]:
    """Follow-up questions for an answer built from ``chunk_ids``.

    Without ``chunk_ids`` this returns starter questions across the knowledge
    base (one per document, alternating modalities). ``doc_ids`` restricts the
    suggestions to those documents, matching a scoped chat. ``nearby`` are
    extra chunks (for example a wider search for the question) that are offered
    after the sibling sections of the documents the answer used.
    """
    used = [c for c in dict.fromkeys(chunk_ids) if c]
    scope = set(doc_ids) if doc_ids else None
    query_l = query.lower()

    docs: list[Document] = []
    if used:
        for cid in used:
            chunk = store.get_chunk(cid)
            if chunk is None or (scope is not None and chunk.doc_id not in scope):
                continue
            doc = store.get_document(chunk.doc_id)
            if doc and doc not in docs:
                docs.append(doc)
    else:
        docs = [d for d in store.list_documents() if scope is None or d.doc_id in scope]
        docs = _interleave_by_modality(sorted(docs, key=lambda d: d.source))

    # Candidate questions per document, in document order, skipping used chunks.
    queues: list[list[tuple[str, Chunk, Document]]] = []
    seen_chunks = set(used)
    for doc in docs:
        queue = []
        for chunk in store.get_document_chunks(doc.doc_id):
            if chunk.chunk_id in seen_chunks:
                continue
            q = question_for(chunk, doc)
            if q:
                queue.append((q, chunk, doc))
        if not used:
            queue = queue[:1]  # starters: one per document
        queues.append(queue)
    extra = []
    for chunk in nearby:
        if chunk.chunk_id in seen_chunks or (scope is not None and chunk.doc_id not in scope):
            continue
        seen_chunks.add(chunk.chunk_id)
        doc = store.get_document(chunk.doc_id)
        q = question_for(chunk, doc)
        if q and doc:
            extra.append((q, chunk, doc))
    queues.append(extra)

    out: list[dict[str, Any]] = []
    asked: set[str] = set()
    while len(out) < limit and any(queues):
        for queue in queues:
            if not queue or len(out) >= limit:
                continue
            q, chunk, doc = queue.pop(0)
            key = q.lower()
            topic = str(chunk.metadata.get("section") or chunk.metadata.get("symbol") or "")
            if key in asked or (topic and topic.lower() in query_l):
                continue
            asked.add(key)
            out.append(
                {
                    "question": q,
                    "doc_id": doc.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "source": Path(doc.source).name,
                    "modality": chunk.modality.value,
                }
            )
    return out
