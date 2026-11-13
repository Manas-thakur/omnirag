---
title: Configuration
description: Every environment variable OmniRAG reads, and what is stored per knowledge base.
---

OmniRAG is configured with environment variables, read when a command or the server starts.
There is no configuration file; per-knowledge-base choices are stored with each knowledge base.

## Environment variables

### Data and defaults

| Variable      | Default      | Meaning                                                              |
| ------------- | ------------ | -------------------------------------------------------------------- |
| `OMNIRAG_HOME` | `~/.omnirag` | data directory for knowledge bases (same as `--data-dir` / `-d`)   |
| `OMNIRAG_KB`  | `default`    | knowledge base used by CLI commands and opened first by `serve`      |

### Ingestion and embeddings

| Variable                | Default   | Meaning                                                                    |
| ----------------------- | --------- | -------------------------------------------------------------------------- |
| `OMNIRAG_EMBEDDER`      | `hashing` | embedder for **new** knowledge bases: `hashing[:dim]`, `st:<hf-model>`, `ollama:<model>` |
| `OMNIRAG_CHUNK_SIZE`    | `1200`    | chunk size in characters for new knowledge bases (at least 50)             |
| `OMNIRAG_CHUNK_OVERLAP` | `150`     | chunk overlap in characters for new knowledge bases (smaller than the size) |
| `OMNIRAG_VLM_MODEL`     | unset     | Ollama vision model for image captions (for example `llava`); unset means metadata only |
| `OMNIRAG_WHISPER_MODEL` | `base`    | faster-whisper model size for audio without a transcript (`audio` extra)   |

### Answering

| Variable               | Default                     | Meaning                                                   |
| ---------------------- | --------------------------- | --------------------------------------------------------- |
| `OMNIRAG_LLM`          | `none`                      | default answer backend: `none`, `ollama[:model]`, `openai[:model]` |
| `OLLAMA_HOST`          | `http://localhost:11434`    | Ollama server (answers, embeddings and image captions)    |
| `OMNIRAG_OLLAMA_MODEL` | `llama3.1:8b`               | Ollama chat model when none is named                      |
| `OPENAI_BASE_URL`      | `https://api.openai.com/v1` | any OpenAI-compatible endpoint                            |
| `OPENAI_API_KEY`       | unset                       | bearer token for that endpoint; required for `api.openai.com` (without it `--llm openai` fails before sending anything) |
| `OMNIRAG_OPENAI_MODEL` | `gpt-4o-mini`               | model name sent to the endpoint when none is named        |
| `OMNIRAG_TIMEOUT`      | `120`                       | HTTP timeout in seconds for model servers                 |

### Server

| Variable                | Default | Meaning                                                                       |
| ----------------------- | ------- | ----------------------------------------------------------------------------- |
| `OMNIRAG_API_KEY`       | unset   | require this key on `/api/*` (`X-API-Key` header or bearer token)              |
| `OMNIRAG_CORS_ORIGINS`  | unset   | comma-separated origins allowed to call the API from a browser (`*` for any)  |
| `OMNIRAG_MAX_UPLOAD_MB` | `50`    | maximum size of one uploaded file, in MB                                      |
| `OMNIRAG_INGEST_ROOTS`  | working directory | folders `POST /api/ingest` may read from, separated by `:` (`;` on Windows); uploads and the CLI are not limited |

Invalid values (`OMNIRAG_CHUNK_SIZE=abc`, an overlap as large as the chunk size) stop every
command with a short error instead of a traceback.

## Stored per knowledge base

| File            | Set by                                   | Contents                                                     |
| --------------- | ---------------------------------------- | ------------------------------------------------------------ |
| `kb.json`       | `kb create`, `kb rebuild --embedder`     | embedder spec, chunk size and overlap (fixed for the KB)      |
| `settings.json` | web app Settings, `PUT .../settings`     | answer backend, model, base URL, top-k (override `OMNIRAG_LLM` for this KB) |

API keys for model endpoints are only ever read from the environment; they are not stored in
`settings.json` and cannot be set from the web app.

## Precedence for the answer backend

1. `--llm` on the CLI, or `llm` in an API request;
2. the knowledge base's `settings.json` (web app **Settings**);
3. `OMNIRAG_LLM`.

The CLI's `omnirag query` uses `--llm` or `OMNIRAG_LLM`; the server and web app also consult the
knowledge base's settings. In the Python API, `kb.ask()` defaults to `"none"`; pass
`llm=kb.default_llm()` to use the knowledge base's settings.
