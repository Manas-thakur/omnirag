---
title: Answers and citations
description: How sources are numbered, how answers cite them, and what the extractive answerer does without a model.
---

## Numbered sources

After retrieval, the top-k results become numbered **sources** `[1]` to `[k]`. They are packed
into a context budget of about 3,000 tokens (estimated at four characters per token), each
preceded by a header with its number, modality and path; neighbouring chunks are included while
they fit. A source records the document and chunk it came from and a human location:

| Modality | Location example                         |
| -------- | ---------------------------------------- |
| text     | `section 'Authentication > Refreshing tokens'`, or `page 3` for PDFs |
| code     | `lines 9-42`                             |
| table    | `rows 1-8`                               |
| audio    | `@ 00:05-01:26`                          |

## With a model

When an LLM backend is configured, the model is instructed to answer only from the numbered
sources and to cite them with `[n]`. Afterwards, citations that point at a number that does not
exist are **removed**, and the answer's `cited` list records which sources were actually used.

If the backend cannot be reached, OmniRAG falls back to the extractive answerer and adds a
warning to the answer instead of failing.

## Without a model (extractive)

The default backend `none` needs no model. The extractive answerer picks the sentences most
relevant to the question from the sources (and a code excerpt when the question is about code)
and cites each one. Answers read as a list of quoted facts rather than prose, but every sentence
is verbatim from a source. The web app marks these answers with *Quoted from sources* and links to
Settings to connect a model.

## In the web app

- A strip of **source cards** sits above the answer, cited sources first and uncited ones
  dashed.
- `[1][2]` in the text renders as one **citation pill** named after the source file
  (`auth.md +1`). When every cited source comes from the same file, the pills show the
  section, lines or rows instead, since identical file names would say nothing.
- **Hovering or focusing** a pill shows the passage with the question's words highlighted;
  clicking opens the source panel with the chunk in context.
- **Copy** copies the answer followed by the list of cited sources.

## In the API

`POST /api/query` returns `answer`, `cited`, `sources` (with `index`, `chunk_id`, `doc_id`,
`source`, `modality`, `location`, `metadata`, `retrieval`), `backend`, `warnings` and `timings`.
The streaming endpoint sends the sources first, then the text, then the same full answer; see
[HTTP API](/omnirag/docs/reference/http-api/#post-apiquerystream).
