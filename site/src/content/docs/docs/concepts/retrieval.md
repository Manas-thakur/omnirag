---
title: Hybrid retrieval
description: Dense and keyword search fused with RRF, re-scored, de-duplicated and widened with neighbouring chunks.
---

Each question runs through the same pipeline, implemented in `omnirag.query` and
`omnirag.retrieve`:

```text
question
  └─ parse: inline filters, quoted phrases, intent, modality hints
       ├─ dense search   (cosine similarity on the embeddings)
       └─ BM25 search    (keyword scores, query expanded with synonyms and abbreviations)
            └─ reciprocal rank fusion (k = 60)
                 └─ lexical reranker (term coverage, exact phrases, modality boosts)
                      └─ MMR de-duplication (λ = 0.75)
                           └─ neighbouring chunks added for context
```

## Parsing the question

The query parser pulls [inline filters](/omnirag/docs/concepts/scoping/#inline-filters) such as
`source:*.py` out of the text, keeps quoted phrases (`"token bucket"`) for the reranker, detects
the intent (factual, explanatory, comparative, procedural, code, summarization or exploratory) and notes **modality
hints**: words like *diagram*, *meeting*, *function* or *CSV* boost a modality without excluding
the others.

## Dense search

Chunks and the question are embedded with the knowledge base's embedder and compared by cosine
similarity. Search is **exact**: a numpy matrix product over all chunks that pass the filters,
with no approximate index. That is fast and simple for tens of thousands of chunks; very large
collections are on the roadmap.

| Embedder spec           | Notes                                                                             |
| ----------------------- | --------------------------------------------------------------------------------- |
| `hashing` / `hashing:N` | Default. Hashing trick over word unigrams, bigrams and character 4-grams with sublinear TF and L2 normalisation; deterministic, offline, 2048 dimensions unless `N` is given |
| `st:<model>`            | sentence-transformers, for example `st:BAAI/bge-small-en-v1.5` (`embeddings` extra) |
| `ollama:<model>`        | an Ollama embedding model, for example `ollama:nomic-embed-text`                  |

Embeddings are cached on disk by model and text hash.

## BM25

A from-scratch BM25 index (k1 = 1.5, b = 0.75) over the same chunks. Text is normalised first:
lower-cased, CamelCase and snake_case identifiers split, stop words dropped and words reduced by a
light Porter-style stemmer, so `expires`, `expired`, `expiry` and `expiration` match each other.

## Fusion, reranking and diversity

- **Reciprocal rank fusion** merges the two ranked lists by rank rather than raw score, so
  neither scale dominates.
- The **lexical reranker** blends the fused score with query-term coverage, exact phrase
  matches and the modality boosts from the router.
- **Maximal marginal relevance** drops near-duplicates, so five sources are five different
  passages.
- Each result can be widened with its **neighbouring chunks** (`neighbors`, default 1).

Each result keeps its ranks from both searches. `omnirag search` prints them, the API returns
them in `retrieval.ranks`, and the web app shows them under *Retrieval details* in the source
preview.

## Modes

`mode` / `--mode` selects `hybrid` (default), `dense` or `bm25` only, which is useful for
comparing the two signals:

```bash
omnirag search "token expiry" --kb notes --mode bm25 -k 5
```

## HyDE

With `--hyde` (CLI) and a configured model, the model first writes a hypothetical answer that is
embedded as a second dense query. It can help short or vague questions; it needs an LLM and is off
by default.
