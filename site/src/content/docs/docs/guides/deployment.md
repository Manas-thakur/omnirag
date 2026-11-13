---
title: Deployment
description: Run OmniRAG in Docker or on a server, with an API key, CORS and sensible limits.
---

`omnirag serve` binds to `127.0.0.1:8000` and is meant for local or trusted-network use. This
page covers running it for other people.

## Docker

```bash
docker run -d --name omnirag -p 8000:8000 -v omnirag-data:/data \
  -e OMNIRAG_API_KEY=change-me \
  ghcr.io/manas-thakur/omnirag:latest
```

The image (built from the repository's `Dockerfile`):

- is based on `python:3.12-slim` and installs the `server`, `pdf` and `images` extras;
- runs as the non-root user `omnirag` (uid 1000) with `OMNIRAG_HOME=/data` as a volume;
- listens on `0.0.0.0:8000` and serves the knowledge base named by `OMNIRAG_KB`
  (default `default`);
- has a health check on `GET /api/health`.

Seed the bundled sample corpus into a `demo` knowledge base and serve it:

```bash
docker run --rm -v omnirag-data:/data ghcr.io/manas-thakur/omnirag omnirag ingest /app/examples/corpus --kb demo
docker run --rm -p 8000:8000 -v omnirag-data:/data -e OMNIRAG_KB=demo ghcr.io/manas-thakur/omnirag
```

To ingest your own folders, mount them read-only, ingest the mount path, and mount the **same
folder at the same path** in the server container. A knowledge base stores the path of every
source file; the server reads the files from there (source previews, raw downloads, re-ingest)
and reports a document as `missing` when its path does not exist inside the container.

```bash
docker run --rm -v omnirag-data:/data -v "$PWD/docs:/docs:ro" \
  ghcr.io/manas-thakur/omnirag omnirag ingest /docs --kb team
docker run -d --name omnirag -p 8000:8000 -v omnirag-data:/data -v "$PWD/docs:/docs:ro" \
  -e OMNIRAG_KB=team ghcr.io/manas-thakur/omnirag
```

To ingest from the running server instead (`POST /api/ingest` or `docker exec`), allow the
mounted folder with `-e OMNIRAG_INGEST_ROOTS=/docs`: by default the server only ingests paths
under its working directory (`/app` in the image).

:::caution
Never run `omnirag kb prune` against a knowledge base whose folders are not mounted where they
were ingested: every document would look missing and prune would remove them all.
:::

## Without Docker

```bash
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag@v0.3.1"
OMNIRAG_API_KEY=change-me omnirag serve --host 0.0.0.0 --port 8000 --kb team
```

Run it under your process manager of choice (systemd, supervisord) and put a reverse proxy with
TLS in front of it. Server-sent events need response buffering off; the server already sends
`X-Accel-Buffering: no` for nginx.

## API key

Set `OMNIRAG_API_KEY` to require a key on every `/api/*` route except `GET /api/health`
and the OpenAPI docs at `/api/docs` (that page loads Swagger UI from a public CDN, so it stays
blank on a machine without internet access; the schema itself is at `/openapi.json`). Clients send it as `X-API-Key: <key>` or
`Authorization: Bearer <key>`. The web app asks for the key once and keeps it in the browser.

```bash
curl -s localhost:8000/api/kbs -H "X-API-Key: change-me"
```

## CORS

CORS is off by default, which is right when the web app and API share an origin. If another
origin must call the API from a browser, list it:

```bash
export OMNIRAG_CORS_ORIGINS=https://intranet.example.com,https://tools.example.com
```

`*` allows any origin. Credentials are never allowed cross-origin; send the API key header.

## What the server protects

- **Uploads** only write inside the knowledge base's `uploads/` folder. File names are reduced
  to a safe base name, only [supported extensions](/omnirag/docs/concepts/modalities/) are
  accepted, and bodies over `OMNIRAG_MAX_UPLOAD_MB` are refused with 413 before they are spooled
  to disk.
- **Raw files** (`GET /api/kbs/{name}/documents/{doc_id}/raw`) are served only for registered
  documents, looked up by id, never by a client path, with a sandboxing Content Security Policy;
  HTML is served as plain text and SVG is sandboxed, so neither runs as active content.
- **The page** is served with a strict Content Security Policy: scripts, fonts and connections
  only from the same origin, no framing.
- Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and
  `X-Frame-Options: DENY`.

:::caution
`POST /api/ingest` reads **paths on the server's filesystem**. It only accepts paths under
`OMNIRAG_INGEST_ROOTS` (a list separated by `:` on Linux and macOS, `;` on Windows; default: the
server's working directory), never ingests OmniRAG's own data directory, and does not follow
links out of an ingested folder. It is protected by the API key like every other route, but
anyone with the key can index any readable file under those roots. Run the server as an
unprivileged user (the Docker image does) and give it access only to what it should index.
:::

## Backups

Each knowledge base is a directory under `OMNIRAG_HOME`. Stop the server (or make sure nothing is
ingesting) and copy the directory; `store.sqlite` holds everything except the embedding cache and
uploads.

## Health and status

- `GET /api/health`: liveness, version, default knowledge base, whether a key is required
  (public).
- `GET /api/status?kb=NAME`: embedder, configured LLM backend and whether it is reachable.
- `omnirag doctor`: the same checks from the command line.
