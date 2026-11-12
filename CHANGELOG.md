# Changelog

All notable changes to OmniRAG are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- **Redesigned web app** (still a no-build page served by FastAPI): a sidebar with
  knowledge bases (create, switch, delete) and conversations, plus Chat, Library and
  Settings views. Light and dark themes that follow the system with a manual toggle,
  layouts down to phone width, keyboard shortcuts (`/` to ask, `Esc` to close panels
  or stop) and explicit empty, loading and error states.
- **Streaming answers** over server-sent events (`POST /api/query/stream`), with a stop
  button, Markdown rendering through a small built-in sanitising renderer, `[n]`
  citation chips that open a source panel (cited chunk highlighted, neighbouring
  chunks, images rendered, code shown with line numbers), modality filter chips,
  copy-answer, and conversation history kept in the browser.
- `LLM.stream()` for Ollama (NDJSON) and OpenAI-compatible endpoints (SSE);
  `AnswerGenerator.stream()` and `KnowledgeBase.ask_stream()` in the Python API.
- **Library**: drag-and-drop or file-picker uploads (`POST /api/kbs/{name}/upload`)
  stored under the knowledge base directory, with per-file progress and ingest
  results; a searchable document table with delete and re-ingest
  (`DELETE /api/kbs/{name}/documents/{id}`, `POST .../reingest`).
- **Per-knowledge-base settings** (`GET/PUT /api/kbs/{name}/settings`): LLM backend
  (server default, none, Ollama, OpenAI-compatible), model, base URL and top-k, saved
  in the KB's `settings.json`.
- `GET /api/status`: embedder in use, the configured LLM backend and whether its
  endpoint is reachable (with latency and the models it lists).
- `DELETE /api/kbs/{name}` and `GET /api/kbs/{name}`.
- **Server hardening**: optional API-key auth (`OMNIRAG_API_KEY`, sent as `X-API-Key`
  or a bearer token; the web UI asks for it once), opt-in CORS
  (`OMNIRAG_CORS_ORIGINS`), an upload size limit (`OMNIRAG_MAX_UPLOAD_MB`, default 50)
  and an extension allow-list, sanitised upload file names, a strict Content Security
  Policy for the page, inert serving of raw source files (sandboxed, HTML and SVG
  never rendered as active content) and `nosniff`/`no-referrer`/`DENY` headers.
- `omnirag doctor`: checks Python, the data directory, the embedder, Ollama and
  OpenAI-compatible reachability and which optional extras are installed
  (`--json`, `--no-network`).
- Release workflow: tags `v*` build the sdist and wheel, create a GitHub Release with
  them attached, push a multi-arch image to `ghcr.io/manas-thakur/omnirag`, and publish
  to PyPI through trusted publishing once the `PYPI_PUBLISH` repository variable is set.

### Changed

- The stemmer is now a light Porter-style stemmer (plurals, `-ed`/`-ing`, `-y`,
  derivational suffixes such as `-ation`, `-ness`, `-ment`), so `expires`, `expired`,
  `expiry` and `expiration` match each other. Short tokens, tokens with digits and
  words ending in `-us`/`-is`/`-os` are left alone.
- Knowledge bases built with the default hashing embedder by 0.1.0 are re-embedded
  automatically the first time they are searched or ingested into, because the
  stemmer feeds the embedding features. This takes about a second per few thousand
  chunks; neural embedders are unaffected.
- `POST /api/query` uses the knowledge base's saved settings when `llm` or `top_k`
  are omitted.
- `/api/kbs` entries include `created_at` and `is_default`; `/api/kbs/{name}/documents`
  entries include `name`, `size_bytes`, `created_at`, `uploaded`, `missing` and
  `warnings`.
- The `server` extra now also installs `python-multipart` (needed for uploads).
- Development status classifier raised to Beta.

## 0.1.0 - 2026-11-13

Untagged initial version.

### Added

- Initial release: multi-modal ingestion (text, PDF, HTML, code, tables, images,
  transcripts and audio), hashing / sentence-transformers / Ollama embedders with an
  on-disk cache, SQLite + numpy vector store, BM25, reciprocal rank fusion, lexical
  reranking, MMR, neighbour chunks, extractive and LLM answers with `[n]` citations,
  named knowledge bases with incremental indexing, the `omnirag` CLI, a FastAPI
  server with a single-page web UI, Docker image and CI.

[Unreleased]: https://github.com/Manas-thakur/omnirag/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Manas-thakur/omnirag/releases/tag/v0.2.0
