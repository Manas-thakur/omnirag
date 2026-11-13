---
title: Troubleshooting and FAQ
description: Fixes for common problems and answers to common questions.
---

Start with `omnirag doctor`. It checks Python, the data directory, the embedder, Ollama and
OpenAI-compatible reachability and the installed extras, and says what to install or set.

## Problems

### `omnirag serve` says the server extra is missing

The web server is optional. Install it with `pip install "omnirag[server]"` (or add `server` to
the extras you already use).

### The web app shows "Server unreachable" or keeps asking for an API key

- Check the server is running and that you opened the address it printed.
- If `OMNIRAG_API_KEY` is set, enter exactly that value. *Settings → Forget key* clears a stored
  key so you can enter a new one.
- Behind a reverse proxy, make sure `/api/*` reaches the server and that response buffering is
  off for `/api/query/stream`, or answers will only appear when they are complete.

### Answers say "Quoted from sources"

That is the offline extractive answerer: no model is configured (the default). Connect one in
*Settings* or with `OMNIRAG_LLM`; see
[Ollama and OpenAI-compatible models](/omnirag/docs/guides/models/).

### Answers include a warning that the model fell back

The configured model endpoint could not be reached or returned an error, so the answer was
produced by the extractive answerer. The *Status* card in Settings and `omnirag doctor` show the
reason (connection refused, unknown model, missing key).

### A PDF produced no chunks

PDF support needs the `pdf` extra (`pypdf`). Scanned PDFs without a text layer have no text to
extract; OCR is not supported yet. The library shows ingest warnings next to the document.

### An image is only described by its file name

Add a sidecar caption (`diagram.png.txt`), reference the image with alt text from a Markdown or
HTML document, or set `OMNIRAG_VLM_MODEL` to an Ollama vision model. See
[Modalities](/omnirag/docs/concepts/modalities/#images).

### An upload is rejected

The library accepts the [supported extensions](/omnirag/docs/concepts/modalities/) up to
`OMNIRAG_MAX_UPLOAD_MB` (50 MB by default) per file. Uploading a file with the same name again
replaces the earlier upload.

### A document shows "missing"

Its source file was moved or deleted after ingestion. Re-ingest it from its new location, delete
it from the library, or run `omnirag kb prune NAME` to remove every missing document.

### Results got worse after changing `OMNIRAG_EMBEDDER`

The embedder is fixed per knowledge base when it is created. Changing the variable only affects
new knowledge bases. Use `omnirag kb rebuild NAME --embedder SPEC` to switch an existing one.

### The question box is disabled

There is no knowledge base yet (create one with **+**), or the knowledge base is empty (add files
in the Library).

### Conversations disappeared

Chat history is kept in the browser's local storage, per browser and per server address. Private
windows, clearing site data or switching browsers start with an empty history.

## FAQ

### Does OmniRAG send my data anywhere?

Not by default. Ingestion, embeddings, search and extractive answers run locally. Data leaves the
machine only if you configure a remote model endpoint (`OPENAI_BASE_URL`), in which case the
question and the numbered source passages are sent to it to write the answer. The web app loads
no third-party scripts or fonts.

### Which file types are supported?

See [Modalities](/omnirag/docs/concepts/modalities/).

### How big can a knowledge base be?

Vector search is exact (no approximate index), which is comfortable for tens of thousands of
chunks on a laptop. Ingestion time is dominated by the embedder; the default hashing embedder
processes the sample corpus in well under a second.

### Can several people use one server?

Yes, behind an API key; see [Deployment](/omnirag/docs/guides/deployment/). There are no user
accounts: everyone with the key sees every knowledge base, and conversations stay in each
person's browser.

### Is there a hosted version?

No. OmniRAG is software you run yourself.

### How do I upgrade?

Install the new version with the same command you used to install it (`pip install --upgrade`,
`uv tool upgrade omnirag`, or pull the new image). Knowledge bases are kept; built with the default
embedder by 0.1.0, they are re-embedded automatically on first use. See the
[changelog](/omnirag/docs/changelog/).
