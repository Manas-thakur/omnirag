---
title: Python API
description: "Use OmniRAG as a library: knowledge bases, ingestion, search, answers and streaming."
---

Everything the CLI and the server do is available from Python. The public names are exported
from the `omnirag` package:

```python
from omnirag import (
    IndexManager,
    KnowledgeBase,
    KnowledgeBaseError,
    IngestReport,
    Answer,
    Source,
    Chunk,
    Document,
    ScoredChunk,
    Modality,
    SearchFilters,
    Settings,
)
```

## Example

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

## `IndexManager`

`IndexManager(home=None, settings=None)` manages the knowledge bases under `home`
(default `OMNIRAG_HOME` or `~/.omnirag`).

| Method                                              | Returns                                 |
| --------------------------------------------------- | --------------------------------------- |
| `create(name, description="", embedder=None)`       | a new `KnowledgeBase`                   |
| `get(name)`                                         | an existing `KnowledgeBase`, or raises `KnowledgeBaseError` |
| `get_or_create(name, **kwargs)`                     | either of the above                     |
| `exists(name)`                                      | `bool`                                  |
| `list()`                                            | the knowledge bases' configurations     |
| `delete(name)`                                      | removes the knowledge base's directory  |

## `KnowledgeBase`

| Method | Description |
| ------ | ----------- |
| `ingest(paths, recursive=True, force=False, progress=None, root=None)` | Ingest files and folders; returns an `IngestReport` with `added`, `updated`, `unchanged`, `failed`, `warnings`, `chunks` and `seconds` |
| `search(query, k=5, filters=None, mode="hybrid", neighbors=1)` | Retrieval only; returns a result with `.results` (`ScoredChunk` objects with `chunk`, `score`, `retrieval`) and `.query` |
| `ask(question, llm="none", k=5, filters=None, mode="hybrid", neighbors=1, hyde=False)` | Retrieve and answer; returns an `Answer` |
| `ask_stream(question, ...)` | Same arguments; yields `("sources", dict)`, then `("delta", str)` pieces, then `("answer", Answer)` |
| `stats()` | Counts by modality, embedder, storage size and timestamps |
| `documents()` | The `Document` records |
| `remove(source)` | Remove one document by source path or id |
| `prune()` | Remove documents whose source files no longer exist |
| `rebuild(embedder=None)` | Re-embed every chunk, optionally switching embedder |
| `close()` | Close the database |

`llm` accepts a backend spec string (`"none"`, `"ollama"`, `"ollama:qwen2.5:7b"`, `"openai"`,
`"openai:gpt-4o"`) or an `LLM` instance. The default is `"none"`, the offline extractive
answerer. To use what the knowledge base's settings (or `OMNIRAG_LLM`) choose, pass
`llm=kb.default_llm()`.

## `Answer` and `Source`

`Answer` has `text`, `backend`, `cited` (the source numbers used), `sources`, `cited_sources`,
`warnings`, `timings` and `to_dict()`. Each `Source` has `index`, `chunk_id`, `doc_id`, `source`,
`title`, `modality`, `score`, `content`, `location`, `metadata`, `retrieval` and `label`.

## Streaming

```python
for event, payload in kb.ask_stream("How are refresh tokens rotated?", llm="ollama"):
    if event == "sources":
        print(len(payload["sources"]), "sources")
    elif event == "delta":
        print(payload, end="", flush=True)
    elif event == "answer":
        print("\ncited:", payload.cited)
```

## Filters

```python
from omnirag import Modality, SearchFilters

SearchFilters(
    modalities=[Modality.CODE],  # only these
    exclude_modalities=[Modality.IMAGE],  # never these
    sources=["*.py"],  # globs or substrings of the source path
    doc_ids=["3f6c0a1e9b2d4c51"],  # only these documents
    metadata={"language": "python"},  # any chunk metadata field
)
```

Inline filters in the question text (`source:*.py`) are parsed in addition to these.

## Your own LLM

Subclass `omnirag.generate.LLM` and implement `complete()` (and optionally `stream()`), then
pass the instance as `llm=`:

```python
from omnirag.generate import LLM


class EchoLLM(LLM):
    name = "echo"

    def complete(self, messages, temperature=0.1, max_tokens=800) -> str:
        return "The sources answer this. [1]"


answer = kb.ask("How are refresh tokens rotated?", llm=EchoLLM())
```

## Settings

`Settings.from_env()` reads the [environment variables](/omnirag/docs/reference/configuration/).
Pass a `Settings` to `IndexManager(settings=...)` to configure a manager explicitly.
