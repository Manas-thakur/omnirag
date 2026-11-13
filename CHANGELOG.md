# Changelog

All notable changes to OmniRAG are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-11-13

### Changed

- **Offline answers are held to a relevance floor.** The extractive answerer weighs question
  words by how rare they are in the knowledge base (BM25 IDF; words it never contains weigh the
  most) and answers "I couldn't find an answer" unless the quoted sentences cover at least half
  of the question's weight. "What is the boiling point of water at sea level?" no longer gets
  cited bullets about anomaly "points" and "levels"; the not-found reply names the closest
  source without citing it.
- Offline answers use section headings (a question about authentication prefers the
  Authentication section), keep short sentences that answer strongly ("Lunch is at one pm."),
  label table cells with their column names, prefer prose over image alt text (unless the
  question asks for a picture), attach a code block only when the question is about code, and
  say when a table listing is partial ("Showing 4 of 12 matching rows in orders.csv").
- "What changed in X 0.3.0?" finds the changelog: change questions match changelog and release
  notes pages, and a heading naming the version asked about ranks and answers first.
- Sources in answers and `omnirag search` are listed in relevance order (MMR still picks a
  diverse set); the CLI column is labelled "relevance".
- `POST /api/ingest` only reads paths under `OMNIRAG_INGEST_ROOTS` (default: the server's
  working directory) and answers `403` otherwise.
- `PUT /api/kbs/{name}/settings` is a partial update: omitted fields keep their saved values.
- Uploads with an unsupported file among supported ones ingest the supported files and report
  the other as `rejected` (only an all-unsupported request gives `415`). `.yaml`, `.yml`,
  `.toml`, `.ini`, `.cfg`, `.log` and `.text` can be uploaded, as they could be ingested from
  disk.
- An inline `modality:` filter with an unknown value is an error, like `--modality`.
- The ingest format changed (exact table values, `(Image: ...)` markers for MDX image
  components), so the next `omnirag ingest` of a folder re-ingests every file once.

### Fixed

- Table row chunks kept only four significant digits (`3035.34` became `3035`, `1999999.99`
  became `2e+06`). Cells are now stored exactly as written; summary means and medians are
  rounded without scientific notation.
- `omnirag kb rebuild NAME -e SPEC` saved the new embedder before checking it, so a bogus spec or
  a missing extra left the knowledge base unusable. The embedder is now validated and every
  chunk embedded first; on failure the old embedder and vectors stay and the CLI prints a clean
  error.
- Invalid embedder specs (`bogus:3`, `hashing:abc`, `st:` without the `embeddings` extra) were
  accepted when creating a knowledge base, from the CLI and `POST /api/kbs`. They are now
  rejected (`400` over HTTP).
- `POST /api/ingest` with an empty path indexed the server's working directory, including its
  log and other knowledge bases. Blank paths are rejected; no ingest (CLI or HTTP) reads files
  inside the OmniRAG data directory (except a knowledge base's own uploads); folder walks no
  longer follow symlinks or junctions out of the folder and skip special files.
- Unexpected server errors return JSON (`{"detail": ...}`, status 500) instead of a plain-text
  page, embedding backend failures return `503`, and a failed upload no longer leaves its file
  behind.
- Offline answers no longer quote Markdown noise: badge and link fragments cut at chunk
  boundaries, code blocks (including halves of one), ASCII and box-drawing diagrams,
  license/copyright lines, inline HTML tags, table header rows, and sentence fragments that
  start mid-sentence. Sentences are no longer split after "e.g.", "i.e.", "etc." or "vs.".
  Bracketed numbers inside quoted text (`items[2]`) are no longer read as citations.
- `--llm openai` without `OPENAI_API_KEY` against the default `api.openai.com` sent the question
  and sources anyway; it now fails before any request. Keyless use still works for custom
  `OPENAI_BASE_URL`s such as local servers.
- `omnirag kb delete` of a knowledge base that is open in the same process no longer fails with
  `PermissionError` (WinError 32) on Windows; if another process holds it, the knowledge base is
  left intact and the error says to stop that process.
- CLI: error messages no longer lose bracketed text to Rich markup (`omnirag[server]`), install
  hints show the GitHub install command (OmniRAG is not on PyPI), and `serve --port 99999`,
  `OMNIRAG_CHUNK_SIZE=abc` and a chunk overlap not smaller than the chunk size give clean errors
  instead of tracebacks.
- CLI: ingesting an empty folder warns, naming an unsupported file warns and exits with status
  1, `search` with no hits prints "No results.", `--hyde` without a model warns, and
  `serve --kb NAME` warns when the knowledge base does not exist yet.
- HTTP: `chunks?window=` accepts only 0-3 (`422` otherwise), the raw file of a document whose
  file is gone gives `410` (like re-ingest), CSV raw files are `text/plain` on every platform,
  and `HEAD /` answers `200`.
- Retrieval on real documentation corpora: chunks are indexed with a context header (path words
  and title), MDX imports/JSX are stripped with front-matter titles used as breadcrumbs, very
  common words are left out of the dense query, and the reranker weighs coverage by IDF and
  matches multi-word phrases from the question.

### Documentation

- Deployment: the Docker recipe for your own folders mounts them at the same path in the server
  container (otherwise every document shows as missing), documents `OMNIRAG_INGEST_ROOTS`, and
  warns against `kb prune` where the folders are not mounted.
- HTTP API: raw-file media types, the per-word `delta` events of offline answers, the CDN that
  `/api/docs` loads Swagger UI from, and the new status codes are described as they are.
- Modalities: 27 code extensions (not 26) and the sniffed text formats; the Python API example
  now creates and ingests the table it searches; install instructions show pinning to a release
  tag.

## [0.3.0] - 2026-11-13

### Added

- **New web app** built with Vite, React 19, TypeScript, Tailwind CSS v4 and shadcn/ui, using
  the shadcn AI Elements patterns (Chat with Message Scroller, Message, Prompt Input, Sources,
  Inline Citation, Suggestion, Chain of Thought on Trace, Context, Code Block). Sources live in
  `web/`; the production build is committed to `src/omnirag/server/static/`, so `pip install`
  still needs no Node.js. It keeps every 0.2 feature and adds:
  - answers whose question heads each block, with Answer, Sources and Media tabs, a strip of
    source cards above the text (cited first), citation pills that name the source with a
    hover/focus preview, and section-labelled pills when one file is cited;
  - progress steps while streaming (searching, reading, writing) that collapse into a
    one-line, expandable summary, and offline "Related" follow-up questions;
  - a home screen with a large composer and starter questions;
  - syntax-highlighted code (answers and source previews, with real line numbers);
  - a context meter that estimates how much source text went to the answerer;
  - a Radix-based sidebar, sheets and bottom drawers on phones, a `Ctrl K` / `⌘ K` command
    palette, toasts with undo, skeleton loading states and a shortcuts dialog.
- **Scoped chats**: tick documents in a Sources panel or in the library to restrict answers to
  them; `POST /api/query` and `/api/query/stream` accept `doc_ids`.
- `POST /api/kbs/{name}/related`: follow-up and starter questions phrased offline from section
  headings, code symbols, table titles and transcript timestamps.
- Self-hosted Inter and JetBrains Mono fonts; the page makes no third-party requests.
- **Documentation site and landing page** (Astro + Starlight, `site/`), published to GitHub
  Pages by `.github/workflows/pages.yml`. The CLI reference is generated from the CLI by
  `scripts/gen_cli_docs.py`.
- CI job for the web app (type check, ESLint, Vitest, build, and a check that the committed
  build is current); the release workflow builds the web app before the Python package.
- `CONTRIBUTING.md`, and `docs/design/references.md` updated with the component kit choice.

### Changed

- Static assets under `/static/assets/` have content-hashed names and are cached for a year;
  the page and other static files are still revalidated on every load.
- The page's Content Security Policy no longer allows Google Fonts, and allows inline
  `style` attributes and elements (used by the UI libraries); scripts remain same-origin only.
- `omnirag query --help` shows "[n] citations" (the brackets were swallowed by the terminal
  markup).

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

[Unreleased]: https://github.com/Manas-thakur/omnirag/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Manas-thakur/omnirag/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Manas-thakur/omnirag/releases/tag/v0.2.0
