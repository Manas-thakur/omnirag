---
title: HTTP API
description: Every endpoint of the OmniRAG server, with request and response shapes.
---

`omnirag serve` exposes a JSON API under `/api`. Interactive OpenAPI docs are served at
`/api/docs`; that page loads Swagger UI from a public CDN, so it is blank without internet
access (the schema itself is at `/openapi.json`). Examples assume the default
`http://localhost:8000`.

## Conventions

- **Authentication:** when `OMNIRAG_API_KEY` is set, every `/api/*` route except
  `GET /api/health` and `/api/docs` needs `X-API-Key: <key>` or `Authorization: Bearer <key>`;
  otherwise the server answers `401` with `{"detail": "missing or invalid API key"}`.
- **Errors** are JSON: `{"detail": "..."}` (or a list of validation errors with status `422`).
  Unknown knowledge bases and documents give `404`; an embedding backend that fails gives `503`;
  an unexpected server error gives `500` with `{"detail": "internal server error (...)"}`.
- **Knowledge base names** appear in paths; omitted `kb` fields mean the server's default
  knowledge base (the one passed to `omnirag serve --kb`).
- **Ids** (`doc_id`, `chunk_id`) are letters, digits, `_` and `-`, up to 80 characters.

## Status

### `GET /api/health`

Liveness. Public even when an API key is required.

```json
{ "status": "ok", "version": "0.3.0", "default_kb": "notes", "llm": "none", "auth_required": false }
```

### `GET /api/status`

Query: `kb` (default: the server default), `probe` (default `true`; `false` skips the network
check).

Returns the version, `auth_required`, `default_kb`, `max_upload_mb`, `upload_extensions`, the
`embedder` of the knowledge base (`spec`, `dimension`, `offline`), the server `defaults` for each
backend, and `llm`:

```json
{
  "backend": "ollama",
  "model": "llama3.1:8b",
  "base_url": "http://localhost:11434",
  "source": "kb",
  "reachable": true,
  "detail": "",
  "latency_ms": 12.5,
  "models": ["llama3.1:8b", "nomic-embed-text"]
}
```

`source` is `kb` when the knowledge base's settings choose the backend and `server` when the
environment does. `backend` is `none` for extractive answers.

## Knowledge bases

### `GET /api/kbs`

A list of knowledge bases: `name`, `description`, `embedder`, `documents`, `chunks`,
`created_at`, `is_default`.

### `POST /api/kbs`

Body: `{"name": "notes", "description": "", "embedder": null}`. Returns `201` with the new
knowledge base, or `400` if the name is invalid or taken or the embedder spec is not valid.
`embedder` takes the same specs as `omnirag kb create --embedder` (`hashing[:dim]` with a
dimension from 16 to 65536, `st:<model>` with the `embeddings` extra installed, or
`ollama:<model>`).

### `GET /api/kbs/{name}`

One knowledge base summary.

### `DELETE /api/kbs/{name}`

Deletes the index, uploads and settings. Files ingested from server paths are not touched.
Returns `{"deleted": "notes"}`.

### `GET /api/kbs/{name}/stats` · `GET /api/stats?kb=NAME`

Statistics: `documents`, `chunks`, `by_modality`, `documents_by_modality`, `embedder`,
`dimension`, `storage_bytes`, `avg_chunk_chars`, `created_at`, `last_updated`, `path`.

### `GET /api/kbs/{name}/settings` · `PUT /api/kbs/{name}/settings`

Per-knowledge-base answer settings:

```json
{ "llm": "ollama", "model": "qwen2.5:7b", "base_url": "", "top_k": 5 }
```

`llm` is `""` (server default), `"none"`, `"ollama"` or `"openai"`; `top_k` is 1–50. Empty
`model` and `base_url` fall back to the environment. `PUT` is a partial update: fields left
out of the body keep their saved values. Saved in the knowledge base's `settings.json`.

## Documents

### `GET /api/kbs/{name}/documents`

```json
[
  {
    "doc_id": "3f6c0a1e9b2d4c51",
    "source": "/home/me/docs/auth.md",
    "path": "docs/auth.md",
    "name": "auth.md",
    "title": "Authentication",
    "modality": "text",
    "chunks": 5,
    "size_bytes": 1642,
    "missing": false,
    "uploaded": false,
    "created_at": "2026-11-13T09:00:00+00:00",
    "updated_at": "2026-11-13T09:00:00+00:00",
    "warnings": []
  }
]
```

`missing` is true when the source file no longer exists; `uploaded` when it was uploaded
through the API.

### `POST /api/kbs/{name}/upload`

Multipart form with one or more `files` fields. Files are stored in the knowledge base's
`uploads/` folder and ingested. A file with an unsupported extension is reported with status
`rejected` while the rest of the batch is ingested; only a request where every file is
unsupported gives `415`. Files over `OMNIRAG_MAX_UPLOAD_MB` give `413`. A file that fails to
ingest is reported as `failed` with its `error` and is not kept on disk.

```bash
curl -s localhost:8000/api/kbs/notes/upload -F files=@handbook.pdf -F files=@schema.sql
```

```json
{
  "files": [
    { "name": "handbook.pdf", "size_bytes": 182311, "status": "added", "error": null,
      "doc_id": "a1b2c3d4e5f60718", "chunks": 42, "warnings": [] }
  ],
  "report": { "added": ["..."], "updated": [], "unchanged": [], "failed": {}, "warnings": {},
              "chunks": 42, "seconds": 0.8, "processed": 1 }
}
```

`status` is `added`, `updated`, `unchanged`, `failed`, `skipped` or `rejected`. The report's
`skipped` map lists paths that were not ingested and why.

### `DELETE /api/kbs/{name}/documents/{doc_id}`

Removes a document from the index, and deletes the stored file if it was uploaded. Returns
`{"deleted": "<doc_id>", "removed_file": true}`.

### `POST /api/kbs/{name}/documents/{doc_id}/reingest`

Re-parses and re-embeds one document from its source file. Returns the updated document and
the ingest report; `410` if the source file is gone.

### `GET /api/kbs/{name}/documents/{doc_id}/raw`

The original file, served inline with a sandboxing Content Security Policy. Images (SVG as
`image/svg+xml`, inert under the sandbox), audio and PDF keep their media type; everything else,
including CSV and HTML, is served as `text/plain`. `410` if the source file is gone (the
document is still indexed; re-ingest it from its new location or delete it).

### `GET /api/kbs/{name}/chunks/{chunk_id}`

Query: `window` (0–3, default 1; other values give `422`). Returns the chunk (`chunk_id`, `position`, `content`,
`metadata`, `doc_id`, `source`, `modality`) with up to `window` neighbouring chunks in `before`
and `after`.

### `POST /api/ingest`

Body: `{"paths": ["/srv/docs"], "kb": "notes", "recursive": true, "force": false}`. Ingests
paths **on the server's filesystem** and creates the knowledge base if needed. Returns the
ingest report. Protect it with an API key before exposing the server.

- An empty or blank path gives `400`.
- Paths must be inside `OMNIRAG_INGEST_ROOTS` (default: the server's working directory);
  others give `403`.
- Files inside OmniRAG's data directory are never ingested, folder walks do not follow links
  that lead outside the folder, and special files (sockets, FIFOs, devices) are skipped.
  Skipped paths are listed in the report's `skipped` map.

## Asking

### `POST /api/query`

```json
{
  "query": "How are refresh tokens rotated?",
  "kb": "notes",
  "top_k": 5,
  "llm": "none",
  "modalities": ["text", "code"],
  "sources": ["*.md"],
  "doc_ids": ["3f6c0a1e9b2d4c51"],
  "mode": "hybrid",
  "neighbors": 1
}
```

Only `query` is required. `top_k` (1–50) and `llm` default to the knowledge base's settings;
`modalities`, `sources` (globs or substrings) and `doc_ids` restrict retrieval; `mode` is
`hybrid`, `dense` or `bm25`; `neighbors` is 0–3.

The response:

```json
{
  "question": "How are refresh tokens rotated?",
  "answer": "- Refresh tokens are rotated: each refresh invalidates the previous one. [1]",
  "backend": "extractive",
  "cited": [1],
  "sources": [
    {
      "index": 1,
      "chunk_id": "3f6c0a1e9b2d4c51-0002",
      "doc_id": "3f6c0a1e9b2d4c51",
      "source": "/home/me/docs/authentication.md",
      "title": "Authentication",
      "modality": "text",
      "score": 0.912,
      "content": "...",
      "snippet": "...",
      "location": "section 'Authentication > Refreshing tokens'",
      "label": "authentication.md section 'Authentication > Refreshing tokens'",
      "metadata": { "path": "docs/authentication.md", "section": "Refreshing tokens" },
      "retrieval": { "ranks": { "dense": 1, "bm25": 1 } },
      "context_before": "",
      "context_after": ""
    }
  ],
  "warnings": [],
  "timings": { "retrieve_ms": 3.1, "generate_ms": 1.2, "total_ms": 4.6 },
  "query": { "text": "How are refresh tokens rotated?", "intent": "exploratory", "mode": "hybrid",
             "modality_hints": [], "filters": { "modalities": [], "sources": [], "doc_ids": [] } }
}
```

### `POST /api/query/stream`

Same body; responds with `text/event-stream`. Events, in order:

| Event     | Data                                                                       |
| --------- | -------------------------------------------------------------------------- |
| `sources` | `{"sources": [...], "query": {...}, "retrieve_ms": 3.1}`, once             |
| `delta`   | `{"text": "..."}`, a piece of the answer, repeated                         |
| `done`    | the full answer, the same shape as `POST /api/query`                       |
| `error`   | `{"detail": "..."}`, sent instead of `done` if generation fails mid-stream |

```bash
curl -N localhost:8000/api/query/stream -H 'content-type: application/json' \
  -d '{"query": "How does authentication work?", "kb": "notes"}'
```

```text
event: sources
data: {"sources": [...], "query": {...}, "retrieve_ms": 2.7}

event: delta
data: {"text": "- Clients call `POST /auth/refresh` ..."}

event: done
data: {"question": "...", "answer": "...", "cited": [1, 2], ...}
```

Each event is an `event:` line, one `data:` line of JSON and a blank line. Model backends stream
token by token; the extractive answerer emits its answer one word (with its trailing space) per
`delta` event.

### `POST /api/kbs/{name}/related`

Follow-up questions phrased offline from the headings, code symbols, table titles and
transcript timestamps of the documents an answer used.

```json
{ "query": "How are refresh tokens rotated?", "chunk_ids": ["3f6c0a1e9b2d4c51-0002"], "doc_ids": null, "limit": 4 }
```

```json
{ "questions": [ { "question": "What does Authentication say about roles?", "doc_id": "...",
                   "chunk_id": "...", "source": "authentication.md", "modality": "text" } ] }
```

Without `chunk_ids`, it returns starter questions across the knowledge base (or across
`doc_ids`). `limit` is 1–10.
