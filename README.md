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
├── server/      FastAPI app + single-file web UI (static/index.html)
├── cli.py       `omnirag` command
└── config.py    environment-based settings
```

## Installation

Requires Python 3.10+.

```bash
# Core (CLI + offline pipeline)
pip install git+https://github.com/Manas-thakur/omnirag

# With the web UI / API server, PDF and image metadata support
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag"
```

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
| `server`     | fastapi, uvicorn        | `omnirag serve`: JSON API + web UI                          |
| `pdf`        | pypdf                   | text extraction from PDFs (per-page chunks)                 |
| `images`     | pillow                  | EXIF metadata and dimensions for JPEG/WebP/... images       |
| `audio`      | faster-whisper          | local transcription of audio files without a transcript     |
| `embeddings` | sentence-transformers   | neural embedders such as `st:BAAI/bge-small-en-v1.5`        |
| `all`        | all of the above        |                                                             |

## Quick start

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

Bring your own LLM by subclassing `omnirag.generate.LLM` and passing the instance as `llm=`.

## Web UI and HTTP API

`omnirag serve` starts a FastAPI app with a single self-contained HTML/JS page (no build step, no
Node toolchain): a chat view with modality filter chips, a knowledge base / LLM selector, and a
source preview panel. Clicking a `[n]` citation shows the chunk, its neighbouring chunks, its
metadata and, for images, the image itself.

> The original plan called for a TypeScript CLI and a React web UI. They were replaced by the
> Python CLI and this no-build page to keep the project a single installable package.

| Method & path | Purpose |
|---------------|---------|
| `GET /api/health` | liveness + version |
| `GET /api/kbs` / `POST /api/kbs` | list / create knowledge bases |
| `GET /api/kbs/{name}/stats`, `GET /api/stats?kb=` | statistics |
| `GET /api/kbs/{name}/documents` | ingested documents |
| `POST /api/query` | `{"query", "kb", "top_k", "llm", "modalities", "sources", "mode", "neighbors"}` → answer, cited ids, sources, timings |
| `POST /api/ingest` | `{"paths": [...], "kb", "recursive", "force"}` (paths on the server's filesystem) |
| `GET /api/kbs/{name}/chunks/{chunk_id}?window=1` | chunk with neighbours (source preview) |
| `GET /api/kbs/{name}/documents/{doc_id}/raw` | original file of an ingested document |
| `GET /api/docs` | interactive OpenAPI docs |

```bash
curl -s localhost:8000/api/query -H 'content-type: application/json' \
  -d '{"query": "How does authentication work?", "kb": "notes", "llm": "none"}'
```

The server is meant for local or trusted-network use: there is no authentication, and the ingest
endpoint reads paths on the server.

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

The embedder and chunking parameters are stored per knowledge base (`kb.json`), so queries always
use the same embedding space as ingestion. Switch with `omnirag kb rebuild NAME --embedder SPEC`.

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

```bash
docker build -t omnirag .
docker run --rm -p 8000:8000 -v omnirag-data:/data omnirag

# seed the bundled demo corpus into the "demo" KB and serve it
docker run --rm -v omnirag-data:/data omnirag omnirag ingest /app/examples/corpus --kb demo
docker run --rm -p 8000:8000 -v omnirag-data:/data -e OMNIRAG_KB=demo omnirag
```

Use `-e OLLAMA_HOST=http://host.docker.internal:11434 -e OMNIRAG_LLM=ollama` to answer with an
Ollama server running on the host.

## Development

```bash
uv sync --extra server --extra pdf --extra images
uv run pytest -q            # offline: no network, no model downloads
uv run ruff check . && uv run ruff format --check .
make demo                   # ingest examples/corpus and run sample queries
make serve                  # web UI on the demo knowledge base
```

CI (`.github/workflows/ci.yml`) runs ruff and pytest on Python 3.10, 3.11 and 3.12 with uv, plus a
CLI smoke test on the sample corpus.

## Roadmap

The design documents in [`plans/`](plans/) describe a larger system. Implemented so far: the full
offline pipeline above, the CLI, the API server and web UI, and the showcase corpus. Not done yet:

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
  verification, streaming responses, tokenizer-accurate budgets.
- **Interfaces:** `omnirag config set`, web UI pages for browsing documents and settings, and the
  planned docs/blog site.

## License

[MIT](LICENSE) © Manas Thakur
