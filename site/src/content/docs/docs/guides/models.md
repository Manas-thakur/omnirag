---
title: Ollama and OpenAI-compatible models
description: Let a language model write the answers, and optionally use model servers for embeddings and image captions.
---

OmniRAG works without any model: retrieval is local and the extractive answerer quotes the
sources. A language model is only used to **write** the answer from the numbered sources (and,
optionally, for HyDE, image captions and embeddings).

## Backends

| Spec                          | Uses                                                        |
| ----------------------------- | ----------------------------------------------------------- |
| `none` (default)              | the offline extractive answerer                             |
| `ollama`, `ollama:<model>`    | Ollama's chat API (`POST /api/chat`) at `OLLAMA_HOST`       |
| `openai`, `openai:<model>`    | any `/chat/completions` endpoint at `OPENAI_BASE_URL`       |

Without a model name, `ollama` uses `OMNIRAG_OLLAMA_MODEL` (default `llama3.1:8b`) and `openai`
uses `OMNIRAG_OPENAI_MODEL` (default `gpt-4o-mini`). Both backends stream tokens to the web app.

The backend can be chosen in three places, from most to least specific:

1. per request: `--llm` on `omnirag query`, or `"llm"` in an API request;
2. per knowledge base: **Settings → Answering** in the web app, or
   `PUT /api/kbs/{name}/settings`;
3. server-wide: the `OMNIRAG_LLM` environment variable.

If the chosen endpoint cannot be reached, the answer falls back to the extractive answerer
with a warning instead of failing. `omnirag doctor` and the web app's **Status** card show
whether endpoints are reachable.

## Ollama

```bash
ollama pull llama3.1:8b
export OMNIRAG_LLM=ollama                      # server-wide default
omnirag query "How does the rate limiter work?" --kb notes --llm ollama:qwen2.5:7b
```

`OLLAMA_HOST` defaults to `http://localhost:11434`. In the web app, pick *Ollama* in Settings;
leave *Model* and *Base URL* empty to use the environment, or fill them in for this knowledge
base. The model field suggests the models the server lists.

## OpenAI-compatible endpoints

Anything that implements `POST {base_url}/chat/completions` works: OpenAI itself, vLLM,
LM Studio, the llama.cpp server and hosted providers with a compatible API.

```bash
export OPENAI_BASE_URL=http://localhost:1234/v1   # LM Studio, for example
export OPENAI_API_KEY=...                          # only if the endpoint needs one
export OMNIRAG_OPENAI_MODEL=my-local-model
omnirag serve --kb notes
```

The key is only read from the server environment. The web app can change the model and base URL
per knowledge base, never the key.

## Embeddings from a model server

Embedders are chosen when a knowledge base is created, or changed with a rebuild:

```bash
omnirag kb create notes --embedder ollama:nomic-embed-text
omnirag kb rebuild notes --embedder st:BAAI/bge-small-en-v1.5   # needs the embeddings extra
```

## Image captions

Set `OMNIRAG_VLM_MODEL` to an Ollama vision model (for example `llava`) to caption PNG, JPEG and
other raster images during ingestion. Without it, images are described from sidecar captions,
alt text and metadata. See [Modalities](/omnirag/docs/concepts/modalities/#images).

## Running in Docker with Ollama on the host

```bash
docker run --rm -p 8000:8000 -v omnirag-data:/data \
  -e OLLAMA_HOST=http://host.docker.internal:11434 -e OMNIRAG_LLM=ollama \
  ghcr.io/manas-thakur/omnirag:latest
```
