# OmniRAG: Multi-Modal RAG Knowledge Assistant

[![CI](https://github.com/Manas-thakur/omnirag/actions/workflows/ci.yml/badge.svg)](https://github.com/Manas-thakur/omnirag/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

OmniRAG is a retrieval-augmented knowledge assistant for **documents, code, tables, images and
audio transcripts**. Point it at a folder, ask questions, and get answers with `[n]` citations
that link back to the exact chunk, line range, table rows or transcript timestamp they came from.

It runs **fully offline by default**: the default embedder, BM25 index, hybrid fusion, reranker
and extractive answerer need nothing beyond `numpy`. Plug in Ollama or any OpenAI-compatible
endpoint when you want an LLM to write the answer.

## Features

- **One index for every modality**: Markdown, HTML, PDF, 25+ programming languages, CSV/JSON
  tables, images (captions, alt text, SVG/PNG/EXIF metadata) and meeting transcripts.
- **Hybrid retrieval built from scratch**: dense vectors + BM25, reciprocal rank fusion, a
  lexical reranker, MMR de-duplication and neighbouring-chunk context.
- **Answers with checked citations**: every claim carries `[n]`; citations that point at
  nothing are removed. Works offline (extractive) or with Ollama / any OpenAI-compatible LLM.
- **Web app**: answers with a source-card strip, citation pills that name the source (hover
  for the excerpt), Answer / Sources / Media tabs, live progress steps and offline "Related"
  follow-ups; tick documents to scope the chat to them; a `Ctrl K` command palette and
  keyboard shortcuts; a document library with drag-and-drop upload; per-knowledge-base model
  settings and a live status check. Light and dark themes, works on a phone, no build step.
- **API and CLI**: FastAPI server with server-sent-event streaming, upload, document and
  settings endpoints; `omnirag` CLI for ingesting, querying and `omnirag doctor`.
- **Safe to expose with care**: optional API key, opt-in CORS, upload size and type limits,
  sanitised file names, strict Content Security Policy.
- **Incremental and portable**: content-hashed re-ingestion, one SQLite file per knowledge
  base, Docker image on ghcr.io.

## Screenshots

An answer with its source strip, citation pills and the preview card of a hovered citation
(light theme):

![Chat view: the question, Answer/Sources/Media tabs, source cards above the answer and a citation preview card](https://raw.githubusercontent.com/Manas-thakur/omnirag/main/docs/screenshots/chat.png)

The library with two documents ticked, which scopes the chat to them (dark theme):

![Library view with two documents selected as the chat scope](https://raw.githubusercontent.com/Manas-thakur/omnirag/main/docs/screenshots/library.png)

<img alt="An answer on a phone-sized screen with the horizontally scrolling source strip" src="https://raw.githubusercontent.com/Manas-thakur/omnirag/main/docs/screenshots/mobile.png" width="300">

The screenshots are captures of the bundled demo corpus with the offline extractive answerer.

## Philosophy

Real knowledge doesn't come only as text:

- **Technical documentation** has diagrams and architecture charts (images)
- **Code repositories** have function definitions and docstrings (code)
- **Meeting recordings** have spoken decisions (audio)
- **Datasets** have schemas and statistics (tables)

The core idea is that **every modality can be mapped into one shared search space using text as
the bridge**. An image is described by its caption, alt text and embedded metadata; a recording by
its transcript; a table by its schema, statistics and rows; code by its signatures and docstrings.
Everything becomes text chunks that live in one index and are searched with one query.

**Built from scratch.** No LangChain, no LlamaIndex. Ingestion, chunking, embedding, the vector
store, BM25, rank fusion, reranking, context assembly, citation tracking and the LLM clients are
all small, readable modules in this repo.

## Architecture

```
Multi-modal sources
  ├── Text    .md .txt .rst .html .pdf
  ├── Code    .py (ast) .js .ts .tsx (regex)  + 20 more languages (line windows)
  ├── Tables  .csv .tsv .json .jsonl
  ├── Images  .png .jpg .svg ...  -> VLM caption | sidecar caption | alt text | SVG/PNG/EXIF metadata
  └── Audio   .vtt .srt transcripts, .mp3/.wav -> sidecar transcript | faster-whisper
         │
         ▼
┌──────────────────────────────┐
│ ingest   detect → parse →    │  omnirag.ingest, omnirag.chunking
│          describe → chunk    │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ embed    hashing (default) | │  omnirag.embed  (+ on-disk embedding cache)
│          sentence-transf. |  │
│          Ollama              │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ store    SQLite: documents,  │  omnirag.store  (exact cosine search on a numpy
│          chunks, metadata,   │                  matrix, metadata filters)
│          vectors             │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ query    filters, intent,    │  omnirag.query
│          rewrite, routing    │
├──────────────────────────────┤
│ retrieve dense + BM25 → RRF  │  omnirag.retrieve
│          → rerank → MMR →    │
│          neighbour chunks    │
├──────────────────────────────┤
│ generate context → LLM or    │  omnirag.generate
│          extractive → cite   │
└──────────────────────────────┘
       index: named knowledge bases, incremental updates (omnirag.index)
       interfaces: CLI (omnirag.cli), FastAPI + web UI (omnirag.server)
```

```
src/omnirag/
├── ingest/      detector, text/pdf/html, code, table, image, audio, orchestrator
├── chunking/    recursive, fixed-size, markdown-heading-aware, line windows
├── embed/       Embedder interface, HashingEmbedder, sentence-transformers, Ollama, cache
├── store/       Document/Chunk/ScoredChunk/SearchFilters models, LocalStore (SQLite + numpy)
├── query/       parser (inline filters, intent, modality hints), rewriter, router
├── retrieve/    BM25 (from scratch), RRF fusion, lexical reranker, MMR, hybrid retriever
├── generate/    context assembly, citation tracker, LLM clients, extractive answerer
├── index/       IndexManager, KnowledgeBase (ingest/search/ask/stats/rebuild/prune)
├── server/      FastAPI app, security middleware, no-build web UI (static/)
├── cli.py       `omnirag` command
├── doctor.py    environment checks behind `omnirag doctor`
├── health.py    Ollama / OpenAI-compatible reachability probes
└── config.py    environment-based settings
```

## Installation

Requires Python 3.10+.

```bash
# From PyPI (once published, see "Releasing" below)
pip install "omnirag[server,pdf,images]"

# From GitHub
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag"

# Core only (CLI + offline pipeline, no web server)
pip install git+https://github.com/Manas-thakur/omnirag

# Docker
docker run --rm -p 8000:8000 -v omnirag-data:/data ghcr.io/manas-thakur/omnirag:latest
```

Check the environment at any time with `omnirag doctor`.

### Development setup (uv)

```bash
git clone https://github.com/Manas-thakur/omnirag
cd omnirag
uv sync --extra server --extra pdf --extra images   # creates .venv with dev tools
uv run pytest -q
uv run ruff check .
uv run omnirag --help
```

`uv sync --all-extras` additionally installs `faster-whisper` and `sentence-transformers`
(large downloads, including PyTorch).

### Optional extras

| Extra        | Installs                | Enables                                                     |
|--------------|-------------------------|-------------------------------------------------------------|
| `server`     | fastapi, uvicorn, python-multipart | `omnirag serve`: JSON API + web UI + uploads     |
| `pdf`        | pypdf                   | text extraction from PDFs (per-page chunks)                 |
| `images`     | pillow                  | EXIF metadata and dimensions for JPEG/WebP/... images       |
| `audio`      | faster-whisper          | local transcription of audio files without a transcript     |
| `embeddings` | sentence-transformers   | neural embedders such as `st:BAAI/bge-small-en-v1.5`        |
| `all`        | all of the above        |                                                             |

## Quick start

The fastest path is the web app:

```bash
pip install "omnirag[server,pdf,images]"
omnirag serve            # http://127.0.0.1:8000
```

1. Click **+** next to *Knowledge bases* and create one (for example `notes`).
2. Open **Library** and drop files onto the page (or use *Choose files*). Each file shows its
   upload progress and how many chunks were indexed.
3. Open **Chat** and ask a question. The answer streams in; click a `[n]` chip to see the exact
   chunk it came from.
4. Optional: in **Settings**, switch the knowledge base to Ollama or an OpenAI-compatible
   endpoint. The status card shows whether the endpoint is reachable.

The same from the command line:

```bash
omnirag kb create notes
omnirag ingest ./docs ./src ./data --kb notes
omnirag stats --kb notes
omnirag query "How does the rate limiter work?" --kb notes             # offline, extractive
omnirag query "How does the rate limiter work?" --kb notes --llm ollama # LLM-written answer
omnirag serve --kb notes                                                # http://127.0.0.1:8000
```

Try it on the bundled sample corpus (docs, Python + TypeScript, CSV, meeting transcript, SVG and
PNG diagrams):

```bash
uv run python examples/run_demo.py      # or: make demo
make serve                              # web UI on the demo knowledge base
```

```
Q: What was decided about the database migration?    [audio transcript]
- [00:15] Marco: For the migration I propose a two-phase approach. [1]
- Decision: we roll out the Redis cache to both regions next sprint, and the migration starts the sprint after. [2]
...
Sources:
 *[1] audio meetings/architecture-review-2026-05-15.vtt (@ 00:05-01:26)
 *[2] audio meetings/architecture-review-2026-05-15.vtt (@ 01:27-01:52)
```

## CLI reference

Global option: `--data-dir/-d PATH` (or `OMNIRAG_HOME`) selects where knowledge bases live
(default `~/.omnirag`). Most commands take `--kb/-b NAME` (default `default`, or `OMNIRAG_KB`).

| Command | Description |
|---------|-------------|
| `omnirag kb create NAME [--embedder SPEC] [--description TEXT]` | Create a knowledge base |
| `omnirag kb list` | List knowledge bases with document/chunk counts |
| `omnirag kb delete NAME [--yes]` | Delete a knowledge base (source files are untouched) |
| `omnirag kb rebuild NAME [--embedder SPEC]` | Re-embed every chunk, optionally with a new embedder |
| `omnirag kb prune NAME` | Remove documents whose source files no longer exist |
| `omnirag ingest PATH... --kb NAME [--no-recursive] [--force] [-q]` | Ingest files/folders; unchanged files are skipped by content hash; creates the KB if missing |
| `omnirag remove SOURCE --kb NAME` | Remove one document |
| `omnirag query "QUESTION" --kb NAME [--llm none\|ollama[:model]\|openai[:model]] [-k 5] [-m MODALITY] [-s GLOB] [--mode hybrid\|dense\|bm25] [--neighbors 1] [--hyde] [--json]` | Answer with citations |
| `omnirag search "TEXT" --kb NAME [-k 10] [-m MODALITY] [--mode ...] [--json]` | Retrieval only: ranked chunks with dense/BM25 ranks |
| `omnirag stats --kb NAME [--json]` | Document/chunk counts by modality, embedder, storage |
| `omnirag serve [--host 127.0.0.1] [--port 8000] [--kb NAME]` | Start the API server and web UI |
| `omnirag doctor [--no-network] [--json]` | Check Python, the data dir, the embedder, Ollama / OpenAI reachability and installed extras; exits 1 on problems |

### Inline query filters

Filters can be typed straight into a question (CLI, API and web UI):

| Syntax | Meaning |
|--------|---------|
| `modality:code` / `type:table` / `m:image,audio` | only these modalities |
| `-modality:image` | exclude a modality |
| `source:*.py` / `file:auth` / `in:docs/` | source path glob or substring |
| `lang:python` | code language |
| `speaker:Priya`, `kind:summary`, `key=value` | any chunk metadata field |
| `"token bucket"` | exact phrase (boosted by the reranker) |

Words like *diagram*, *meeting*, *function* or *CSV* act as soft hints that boost a modality
without excluding the others.

## Python API

```python
from omnirag import IndexManager, Modality, SearchFilters

manager = IndexManager()  # uses $OMNIRAG_HOME or ~/.omnirag
kb = manager.get_or_create("notes")

report = kb.ingest(["./docs", "./src"])  # incremental: re-running skips unchanged files
print(len(report.added), "added,", report.chunks, "chunks")

answer = kb.ask("How are refresh tokens rotated?", llm="none", k=5)
print(answer.text)  # sentences with [n] citations
for src in answer.cited_sources:
    print(src.index, src.modality, src.metadata["path"], src.location)

# Retrieval only, with filters
hits = kb.search("p95 latency", k=3, filters=SearchFilters(modalities=[Modality.TABLE]))
for hit in hits.results:
    print(round(hit.score, 3), hit.chunk.source, hit.retrieval["ranks"])

kb.close()
```

Stream an answer as it is generated:

```python
for event, payload in kb.ask_stream("How are refresh tokens rotated?", llm="ollama"):
    if event == "sources":
        print(len(payload["sources"]), "sources")
    elif event == "delta":
        print(payload, end="", flush=True)
    elif event == "answer":
        print("\ncited:", payload.cited)
```

Bring your own LLM by subclassing `omnirag.generate.LLM` (implement `complete()`, and optionally
`stream()`) and passing the instance as `llm=`.

## Web UI and HTTP API

`omnirag serve` starts a FastAPI app that serves the API and a web app made of plain HTML, CSS
and JavaScript (`src/omnirag/server/static/`): no Node toolchain, no build step and no CDN
scripts, so it works offline.

- **Sidebar**: knowledge bases (create, switch, delete with confirmation), recent
  conversations of the active knowledge base (kept in the browser's local storage) and a model
  status indicator.
- **Home**: an empty chat shows "Ask &lt;kb&gt; anything" with a large composer and starter
  questions drawn from the knowledge base; after the first question the composer docks at the
  bottom.
- **Answers**: each question heads its own block with **Answer · Sources · Media** tabs (Media
  only when images were retrieved). Progress steps (searching, reading, writing) collapse into
  "Answered from K sources in 0.4s", expandable to timings. A strip of source cards (file,
  section / lines / rows / timestamp, image thumbnails; cited first) sits above the text, which
  is set in a reading face in a narrow column. Citations render as pills with the source's file
  name ("auth.md +1"); hovering or focusing one shows the excerpt, clicking opens the source
  panel with the chunk highlighted among its neighbours, images displayed and code shown with
  real line numbers. "Related" questions are suggested offline from neighbouring sections.
  Answers stream over server-sent events and can be stopped or copied (with their source list);
  Markdown is rendered by a small built-in renderer that escapes everything first, so model
  output cannot inject HTML.
- **Scoping**: tick documents in the **Sources** panel (top-bar button, or `S`) or in the
  library; questions then only search those documents and a "Scoped to N sources" chip appears
  above the composer. Modality chips and inline filters such as `source:*.py` still work.
- **Library**: drag-and-drop or file-picker upload with per-file progress, and a filterable
  document table (name, type, chunks, size, ingested) with selection, re-ingest and delete.
- **Settings**: LLM backend (server default, none, Ollama, OpenAI-compatible), model, base URL
  and top-k, saved per knowledge base; the embedder in use and whether the model endpoint is
  reachable; theme (system, light, dark); API key.
- **Keyboard**: `Ctrl K` / `⌘ K` opens a command palette (new chat, switch knowledge base, open
  a document, go to a view, choose or clear sources, toggle theme); `?` lists shortcuts; `/`
  focuses the question box; `N` starts a new chat; `G` then `C` / `L` / `S` switches views;
  `Esc` stops generation or closes panels.

The interaction patterns follow Perplexity's answer page, NotebookLM's source selection and
Linear's app shell; [docs/design/references.md](docs/design/references.md) lists what was
adopted from each and why.

> The original plan called for a TypeScript CLI and a React web UI. They were replaced by the
> Python CLI and this no-build app to keep the project a single installable package.

### API reference

All endpoints live under `/api`; interactive docs are at `/api/docs`. When `OMNIRAG_API_KEY`
is set, send it as `X-API-Key: <key>` (or `Authorization: Bearer <key>`) on every request except
`GET /api/health`.

| Method & path | Purpose |
|---------------|---------|
| `GET /api/health` | liveness, version, default KB, whether an API key is required |
| `GET /api/status?kb=&probe=true` | embedder in use, configured LLM backend/model/URL, whether it is reachable (latency, listed models), upload limits |
| `GET /api/kbs` / `POST /api/kbs` | list / create knowledge bases (`{"name", "description", "embedder"}`) |
| `GET /api/kbs/{name}` / `DELETE /api/kbs/{name}` | knowledge base summary / delete it with its index, uploads and settings |
| `GET /api/kbs/{name}/settings` / `PUT ...` | per-KB answer settings `{"llm": ""\|"none"\|"ollama"\|"openai", "model", "base_url", "top_k"}` |
| `GET /api/kbs/{name}/stats`, `GET /api/stats?kb=` | statistics |
| `GET /api/kbs/{name}/documents` | documents with name, path, modality, chunks, size, timestamps, `uploaded`, `missing` |
| `POST /api/kbs/{name}/upload` | multipart `files` (one or more); stored in the KB's `uploads/` folder and ingested; returns per-file status |
| `DELETE /api/kbs/{name}/documents/{doc_id}` | remove a document (and its uploaded file, if it was uploaded) |
| `POST /api/kbs/{name}/documents/{doc_id}/reingest` | re-parse and re-embed one document |
| `POST /api/query` | `{"query", "kb", "top_k", "llm", "modalities", "sources", "doc_ids", "mode", "neighbors"}` → answer, cited ids, sources, timings; `doc_ids` restricts retrieval to those documents |
| `POST /api/query/stream` | same body; `text/event-stream` with `sources`, `delta` (`{"text"}`) …, then `done` (the full answer) or `error` |
| `POST /api/ingest` | `{"paths": [...], "kb", "recursive", "force"}` (paths on the server's filesystem) |
| `POST /api/kbs/{name}/related` | `{"query", "chunk_ids", "doc_ids", "limit"}` → follow-up questions phrased offline from the headings, symbols and titles of the documents those chunks belong to; without `chunk_ids`, starter questions across the knowledge base |
| `GET /api/kbs/{name}/chunks/{chunk_id}?window=1` | chunk with neighbours (source preview) |
| `GET /api/kbs/{name}/documents/{doc_id}/raw` | original file of a registered document, served inert |

`top_k` and `llm` may be omitted from queries; the knowledge base's saved settings are used.

```bash
curl -s localhost:8000/api/query -H 'content-type: application/json' \
  -d '{"query": "How does authentication work?", "kb": "notes", "llm": "none"}'

curl -N localhost:8000/api/query/stream -H 'content-type: application/json' \
  -d '{"query": "How does authentication work?", "kb": "notes"}'

curl -s localhost:8000/api/kbs/notes/upload -F files=@handbook.pdf -F files=@schema.sql
```

### Security

The server binds to `127.0.0.1` by default and is meant for local or trusted networks. Before
exposing it:

- set `OMNIRAG_API_KEY` (the web app asks for the key once and keeps it in the browser);
- leave CORS off unless another origin must call the API, then list it in
  `OMNIRAG_CORS_ORIGINS`;
- remember that `POST /api/ingest` reads paths on the server's filesystem (protected by the key
  like every other endpoint), while uploads only ever write into the knowledge base directory.

Uploads are limited by size (`OMNIRAG_MAX_UPLOAD_MB`) and to file types the ingestors support;
file names are reduced to a safe basename. Raw source files are only served for registered
documents (looked up by id, never by path) with a sandboxing Content Security Policy, and HTML
or SVG content is never rendered as an active page.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `OMNIRAG_HOME` | `~/.omnirag` | data directory for knowledge bases |
| `OMNIRAG_KB` | `default` | default knowledge base for CLI commands |
| `OMNIRAG_EMBEDDER` | `hashing` | embedder for new KBs: `hashing[:dim]`, `st:<hf-model>`, `ollama:<model>` |
| `OMNIRAG_LLM` | `none` | default answer backend: `none`, `ollama[:model]`, `openai[:model]` |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server (LLM, embeddings, VLM captions) |
| `OMNIRAG_OLLAMA_MODEL` | `llama3.1:8b` | Ollama chat model |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint (OpenAI, vLLM, LM Studio, llama.cpp server, ...) |
| `OPENAI_API_KEY` | unset | bearer token for that endpoint |
| `OMNIRAG_OPENAI_MODEL` | `gpt-4o-mini` | model name sent to the endpoint |
| `OMNIRAG_VLM_MODEL` | unset | Ollama vision model for image captions (e.g. `llava`); unset = metadata-only |
| `OMNIRAG_WHISPER_MODEL` | `base` | faster-whisper model size (with the `audio` extra) |
| `OMNIRAG_CHUNK_SIZE` / `OMNIRAG_CHUNK_OVERLAP` | `1200` / `150` | chunk size/overlap in characters for new KBs |
| `OMNIRAG_TIMEOUT` | `120` | HTTP timeout (seconds) for model servers |
| `OMNIRAG_API_KEY` | unset | require this key on `/api/*` (`X-API-Key` header or bearer token) |
| `OMNIRAG_CORS_ORIGINS` | unset | comma-separated origins allowed to call the API from a browser (`*` for any) |
| `OMNIRAG_MAX_UPLOAD_MB` | `50` | maximum size of one uploaded file |

The embedder and chunking parameters are stored per knowledge base (`kb.json`), so queries always
use the same embedding space as ingestion. Switch with `omnirag kb rebuild NAME --embedder SPEC`.
Answer settings chosen in the web app (backend, model, base URL, top-k) are stored per knowledge
base in `settings.json` and override `OMNIRAG_LLM` for that knowledge base; API keys are only
read from the environment.

If an LLM backend is unreachable, OmniRAG falls back to the extractive answerer and prints a
warning instead of failing.

## How it works

- **Ingestion.** Files are routed by extension (with a content sniff for unknown text files).
  Markdown is split on headings and every chunk carries its heading breadcrumb; HTML is converted
  to structured text; PDFs are chunked per page. Python is parsed with `ast` into module, class,
  function and (for large classes) method chunks with signatures and docstrings; JS/TS
  declarations are found with regexes; other languages use overlapping line windows. Tables get a
  summary chunk (column types, min/max/mean/median, frequent values) plus row chunks rendered as
  `column=value`. Images are described from a VLM caption, a sidecar caption file
  (`img.png.txt`, `img.caption.txt` or `img.txt`), alt text found in Markdown/HTML that references
  the image, SVG `<title>/<desc>/<text>`, PNG text chunks, EXIF, and finally the file name.
  Transcripts (`.vtt`/`.srt`, or a sidecar next to an audio file) keep timestamps and speakers.
- **Incremental indexing.** Each document is keyed by its absolute path and a content hash
  (including sidecar captions). Re-ingesting skips unchanged files and atomically replaces
  changed ones. Embeddings are cached on disk by model and text hash.
- **Text normalisation.** Tokens are lower-cased, CamelCase/snake_case identifiers are split,
  stopwords dropped and words reduced by a light Porter-style stemmer, so `expires`, `expired`,
  `expiry` and `expiration` all match. Short tokens and tokens with digits are left alone.
- **Embeddings.** The default `HashingEmbedder` uses the hashing trick over word unigrams, bigrams
  and character 4-grams with sublinear TF and L2 normalisation: deterministic, offline, no
  downloads. Neural embedders are one flag away.
- **Retrieval.** Dense cosine search and BM25 (from scratch, with a synonym/abbreviation-expanded
  query) each return candidates, which are fused with Reciprocal Rank Fusion. A lexical reranker
  blends the fused score with query-term coverage, exact-phrase matches and modality boosts from
  the router, then MMR removes near-duplicates and each hit is augmented with its neighbouring
  chunks. Optional HyDE adds an LLM-written hypothetical passage as a second dense query.
- **Generation.** Sources are numbered and packed into a token budget. An LLM is instructed to cite
  with `[n]`; citations pointing at non-existent sources are stripped. Without an LLM, the
  extractive answerer picks the most query-relevant sentences (and a code excerpt when relevant)
  and cites each one.

## Docker

Released images are published to `ghcr.io/manas-thakur/omnirag` (tags `latest`, `0.2.0`,
`0.2`, for linux/amd64 and linux/arm64). To build locally:

```bash
docker build -t omnirag .
docker run --rm -p 8000:8000 -v omnirag-data:/data omnirag

# seed the bundled demo corpus into the "demo" KB and serve it
docker run --rm -v omnirag-data:/data omnirag omnirag ingest /app/examples/corpus --kb demo
docker run --rm -p 8000:8000 -v omnirag-data:/data -e OMNIRAG_KB=demo omnirag
```

Use `-e OLLAMA_HOST=http://host.docker.internal:11434 -e OMNIRAG_LLM=ollama` to answer with an
Ollama server running on the host, and `-e OMNIRAG_API_KEY=...` before publishing the port
beyond your machine.

## Development

```bash
uv sync --extra server --extra pdf --extra images
uv run pytest -q            # offline: no network, no model downloads
uv run ruff check . && uv run ruff format --check .
uv run omnirag doctor       # environment check
make demo                   # ingest examples/corpus and run sample queries
make serve                  # web UI on the demo knowledge base
```

The web app is plain files in `src/omnirag/server/static/` (`index.html`, `app.css`,
`app.js`, `markdown.js`); edit and reload, there is nothing to build.

CI (`.github/workflows/ci.yml`) runs ruff and pytest on Python 3.10, 3.11 and 3.12 with uv, plus a
CLI smoke test on the sample corpus.

## Releasing

`.github/workflows/release.yml` runs when a tag matching `v*` is pushed:

1. **build**: checks that the tag matches the version in `pyproject.toml` and
   `omnirag/__init__.py`, runs the tests, builds the sdist and wheel with `uv build` and
   smoke-tests the wheel (`omnirag --version`, `omnirag doctor`).
2. **github-release**: creates a GitHub Release for the tag with both files attached and the
   matching section of `CHANGELOG.md` as release notes (tags containing `-`, such as
   `v0.3.0-rc1`, are marked as pre-releases).
3. **docker**: builds the image for linux/amd64 and linux/arm64 and pushes it to
   `ghcr.io/manas-thakur/omnirag` with the `GITHUB_TOKEN` (no extra secrets).
4. **pypi**: publishes the same files to PyPI with trusted publishing. It is skipped until the
   repository variable `PYPI_PUBLISH` is set to `true`, so releases work before PyPI is set up.

To cut a release:

```bash
# bump the version in pyproject.toml and src/omnirag/__init__.py, update CHANGELOG.md
uv lock
git commit -am "Release 0.2.0"
git tag v0.2.0
git push origin main v0.2.0
```

One-time PyPI setup: on PyPI add a *pending trusted publisher* for project `omnirag` with owner
`Manas-thakur`, repository `omnirag`, workflow `release.yml` and environment `pypi`; create a
GitHub environment named `pypi` (optionally with required reviewers); then set the repository
variable `PYPI_PUBLISH=true`. After the first image push, make the ghcr.io package public in
its package settings if it should be pullable without logging in.

## Roadmap

The design documents in [`plans/`](plans/) describe a larger system. Implemented so far: the full
offline pipeline above, the CLI, the API server and web app, and the showcase corpus. Not done yet:

- **Ingest:** OCR for scanned PDFs/images (Surya), PDF embedded-image extraction, Hugging Face
  VLM captioners (only Ollama vision models are supported), URL/web ingestion, EPUB, Parquet and
  XLSX, speaker diarization and audio summaries, tree-sitter parsing for non-Python languages.
- **Embed:** CLIP/SigLIP image embeddings and image-to-image search, int8/binary quantization.
- **Store/index:** ANN indexes (HNSW/IVF) and external backends (LanceDB, pgvector, PostgreSQL
  metadata); search is currently exact brute force, fine for tens of thousands of chunks. KB
  merge, sharding, export/import.
- **Query:** LLM-based query decomposition and step-back rewriting (HyDE is implemented).
- **Retrieve:** cross-encoder reranking (e.g. `bge-reranker`), retrieval evaluation metrics
  (recall@k, MRR, nDCG) and an eval job in CI.
- **Generate:** multi-pass outline/draft/critique/revise generation, LLM-based citation
  verification, tokenizer-accurate budgets.
- **Interfaces:** `omnirag config set`, server-side conversation history shared across
  devices, user accounts, and the planned docs/blog site.

## License

[MIT](LICENSE) © Manas Thakur
