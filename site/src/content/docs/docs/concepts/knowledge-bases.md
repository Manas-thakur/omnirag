---
title: Knowledge bases
description: Named, self-contained indexes with their own embedder, documents, settings and uploads.
---

A **knowledge base** (KB) is a named, self-contained index. Each one has its own documents,
chunks, embeddings, answer settings and uploaded files, and is searched on its own. Use one per
project, team or corpus: `work`, `handbook`, `demo`.

## On disk

Knowledge bases live under `OMNIRAG_HOME` (default `~/.omnirag`), in `kbs/<name>/`:

| File                  | Contents                                                                  |
| --------------------- | ------------------------------------------------------------------------- |
| `kb.json`             | name, description, embedder spec, chunk size and overlap, creation time   |
| `store.sqlite`        | documents, chunks, metadata and vectors (with SQLite WAL files beside it) |
| `embed_cache.sqlite`  | embeddings cached by model and text hash, so re-ingesting is cheap        |
| `settings.json`       | answer settings chosen in the web app (backend, model, base URL, top-k)   |
| `uploads/`            | files uploaded through the web app or `POST /api/kbs/{name}/upload`       |

Files ingested from paths on disk are **not copied**: the KB stores their text, chunks and
location, and reads the original only when you open or re-ingest it.

## Names

Names use letters, digits, dots, dashes and underscores and start with a letter or digit
(at most 64 characters). The CLI uses `default` unless you pass `--kb` or set `OMNIRAG_KB`;
`omnirag serve --kb NAME` sets which KB the web app opens first.

## Fixed per knowledge base

The **embedder** and the **chunk size and overlap** are recorded in `kb.json` when the KB is
created, so queries always use the same embedding space as ingestion. To switch embedder,
rebuild:

```bash
omnirag kb rebuild notes --embedder st:BAAI/bge-small-en-v1.5
```

Answer settings are different: they can change at any time, per KB, in the web app's
**Settings** or through `PUT /api/kbs/{name}/settings`. They override the server-wide
`OMNIRAG_LLM` default for that KB.

## Incremental updates

Each document is keyed by its absolute path and a content hash (which also covers sidecar
caption and transcript files). Re-running `omnirag ingest` skips unchanged files and atomically
replaces changed ones; `--force` re-ingests everything. `omnirag kb prune NAME` removes documents
whose source files are gone, and `omnirag remove SOURCE` removes one document.

## Lifecycle

```bash
omnirag kb create notes --description "Team notes"
omnirag kb list
omnirag stats --kb notes
omnirag kb delete notes --yes   # removes the index, uploads and settings, never your source files
```

The web app offers the same: **+** next to *Knowledge bases* to create one, the trash icon or
*Settings → Delete knowledge base* to delete it.
