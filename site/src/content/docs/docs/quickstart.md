---
title: Quickstart
description: Index the bundled sample corpus, ask a question from the terminal and open the web app.
---

This walk-through uses the sample corpus in the repository's `examples/corpus` folder: Markdown
and HTML docs, Python and TypeScript sources, a CSV of latency benchmarks, a meeting transcript,
and an SVG and a PNG diagram. Everything runs offline.

## 1. Install

```bash
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag"
git clone https://github.com/Manas-thakur/omnirag   # for the sample corpus
cd omnirag
```

## 2. Create a knowledge base and ingest

```bash
omnirag kb create notes --description "Team notes"
omnirag ingest examples/corpus --kb notes
```

```text
notes: 10 added, 0 updated, 0 unchanged, 0 failed - 30 chunks in 0.35s
```

`ingest` creates the knowledge base if it does not exist yet, so the first command is optional.
Run it again and every file is skipped, because nothing changed:
documents are keyed by path and content hash.

## 3. Ask from the terminal

```bash
omnirag query "How does the rate limiter work?" --kb notes
```

The answer is printed with `[n]` markers, followed by the numbered sources with their
location: a section for Markdown, a line range for code, a row range for tables and a
timestamp for transcripts. Add `--json` for the full result, including retrieval scores and
timings.

Try questions that hit other modalities:

```bash
omnirag query "What was decided about the database migration?" --kb notes   # transcript
omnirag query "What does the latency benchmark table contain?" --kb notes     # CSV table
omnirag query "What does the deployment topology diagram show?" --kb notes   # PNG + caption
```

Filters can be typed into the question, for example `source:*.py` or `modality:table`; see
[Scoping](/omnirag/docs/concepts/scoping/).

## 4. Open the web app

```bash
omnirag serve --kb notes
```

Open `http://127.0.0.1:8000`. The home screen suggests a few starter questions drawn from the
knowledge base's headings and symbols. Ask one: sources appear above the answer, citation pills
follow each sentence, and a hover shows the passage. The
[web app guide](/omnirag/docs/guides/web-app/) covers the rest.

## 5. Use your own files

```bash
omnirag ingest ~/notes ~/code/my-service --kb work
omnirag serve --kb work
```

Or create a knowledge base in the web app (the **+** next to *Knowledge bases*) and drop files
into **Library**.

## 6. Optional: let a model write the answers

With [Ollama](https://ollama.com) running locally:

```bash
ollama pull llama3.1:8b
omnirag query "How does the rate limiter work?" --kb notes --llm ollama
```

Or pick **Ollama** in the web app's **Settings** for that knowledge base. Any
OpenAI-compatible endpoint works too; see
[Ollama and OpenAI-compatible models](/omnirag/docs/guides/models/).
