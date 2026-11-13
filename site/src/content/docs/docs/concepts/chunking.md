---
title: Chunking
description: How files are split into chunks, and why the split follows each file's structure.
---

Retrieval works on **chunks**: passages small enough to match a question precisely and to fit
several into a model's context, but large enough to make sense on their own. OmniRAG splits each
file along its natural structure instead of at fixed character offsets.

## Size and overlap

New knowledge bases use a chunk size of **1200 characters** with **150 characters** of overlap,
set by `OMNIRAG_CHUNK_SIZE` and `OMNIRAG_CHUNK_OVERLAP`. The values are stored in the KB's
`kb.json`; changing the environment later does not affect existing knowledge bases.

## Strategies

| Content            | Strategy                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------ |
| Markdown           | One section per heading; long sections are split recursively; each chunk starts with its heading breadcrumb |
| Plain text, HTML   | Recursive splitting on paragraphs, then lines, then sentences, then words, with overlap    |
| PDF                | Per page, then recursive splitting                                                         |
| Python             | Module, class, function and method chunks from the syntax tree, with signatures and docstrings |
| JS / TS            | Declarations found by pattern                                                              |
| Other code         | Overlapping line windows with line numbers                                                 |
| Tables             | One summary chunk plus row-range chunks rendered as `column=value`                         |
| Transcripts        | Groups of cues with their timestamps and speakers                                          |
| Images             | One chunk with the description                                                             |

## Metadata

Every chunk carries metadata that the rest of the pipeline uses:

- `path` (relative to the ingested folder), `title` and `modality`;
- `heading` / `section` for documents, `symbol`, `kind`, `language`, `line_start` and
  `line_end` for code, `row_start` and `row_end` for tables, `timestamp` and `speakers` for
  transcripts, `page` for PDFs.

This is what lets citations say *where* in a file an answer came from, and what the offline
"Related questions" are phrased from. Any metadata field can also be used as a filter, for
example `kind:summary` (table summaries) or `lang:python`.

## Neighbours

Chunks keep their position in the document. At query time each retrieved chunk can be widened
with its neighbours (`--neighbors`, default 1, at most 3), so an answer sees the paragraph
before and after the best match without making every chunk large.
