---
title: Scoping
description: Restrict answers to chosen documents, content types or paths.
---

By default a question searches the whole knowledge base. Three ways narrow it down, and they
combine.

## Selected documents

Choose documents and only those are searched, like a notebook of sources.

- **Web app:** tick documents in the **Sources** panel (top bar, or press `S`) or in the
  **Library** table. A *Scoped to N sources* chip appears above the question box, the top bar
  shows `Sources N/total`, and each answer records the scope it was asked with. The selection is
  kept per knowledge base in the browser. Clear it with the chip's ×, *Use all sources* or the
  command palette.
- **API:** send `doc_ids` with `POST /api/query` or `/api/query/stream`:

```bash
curl -s localhost:8000/api/query -H 'content-type: application/json' \
  -d '{"query": "How are refresh tokens rotated?", "kb": "notes", "doc_ids": ["<doc_id>"]}'
```

Document ids come from `GET /api/kbs/{name}/documents`.

## Content types

- **Web app:** the *All types* menu in the question box limits answers to text, code, tables,
  images or audio.
- **CLI:** `--modality` / `-m`, repeatable: `omnirag query "..." -m code -m table`.
- **API:** `"modalities": ["code", "table"]`.

## Inline filters

Filters can be typed straight into a question, in the CLI, the API and the web app:

| Syntax                                       | Meaning                                  |
| -------------------------------------------- | ---------------------------------------- |
| `modality:code`, `type:table`, `m:image,audio` | only these modalities                  |
| `-modality:image`                            | exclude a modality                       |
| `source:*.py`, `file:auth`, `in:docs/`       | source path glob or substring            |
| `lang:python`                                | code language                            |
| `kind:summary`, `key=value`                  | any chunk metadata field                 |
| `"token bucket"`                             | exact phrase, boosted by the reranker    |

The filters are removed from the text before it is searched. The CLI's `--source` / `-s` option
and the API's `sources` field take the same globs and substrings.
