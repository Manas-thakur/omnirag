# Changelog

All notable changes to OmniRAG are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
