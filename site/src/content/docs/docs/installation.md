---
title: Installation
description: Install OmniRAG with pip, uv or Docker, or run it from a source checkout.
---

OmniRAG is a Python package that needs **Python 3.10 or newer**. The web app is shipped
pre-built inside the package, so no Node.js toolchain is needed to run it.

## With pip

```bash
# From GitHub (core + web server + PDF + image metadata), latest main
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag"

# The same, pinned to a release tag
pip install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag@v0.3.0"

# From a downloaded release wheel (GitHub Releases page)
pip install "omnirag-0.3.0-py3-none-any.whl[server,pdf,images]"

# Core only: the CLI and the offline pipeline, no web server
pip install "omnirag @ git+https://github.com/Manas-thakur/omnirag"
```

:::note
Publishing to PyPI is wired into the release workflow but switched off until the project's
trusted publisher is configured. Once it is, `pip install "omnirag[server,pdf,images]"` works
too. Until then, install from GitHub or a release wheel.
:::

Check the result:

```bash
omnirag --version
omnirag doctor
```

`omnirag doctor` checks Python, the data directory, the embedder, Ollama and
OpenAI-compatible reachability and which optional extras are installed. It exits with status 1
if something is wrong; `--no-network` skips the model-server probes and `--json` prints the
checks as JSON.

## With uv

```bash
# As a standalone tool on your PATH (append @v0.3.0 to pin a release)
uv tool install "omnirag[server,pdf,images] @ git+https://github.com/Manas-thakur/omnirag"

# Or run once without installing
uvx --from "omnirag[server] @ git+https://github.com/Manas-thakur/omnirag" omnirag serve
```

## Optional extras

| Extra        | Installs                           | Enables                                                   |
| ------------ | ---------------------------------- | --------------------------------------------------------- |
| `server`     | fastapi, uvicorn, python-multipart | `omnirag serve`: HTTP API, web app and uploads            |
| `pdf`        | pypdf                              | text extraction from PDFs (one chunk group per page)      |
| `images`     | pillow                             | EXIF metadata and dimensions for JPEG, WebP and others    |
| `audio`      | faster-whisper                     | local transcription of audio files without a transcript   |
| `embeddings` | sentence-transformers              | neural embedders such as `st:BAAI/bge-small-en-v1.5`      |
| `all`        | all of the above                   |                                                           |

`audio` and `embeddings` pull in PyTorch and model downloads; the others are small.

## Docker (GHCR)

Tagged releases publish a multi-architecture image (linux/amd64 and linux/arm64) to the
GitHub Container Registry. It contains the `server`, `pdf` and `images` extras, runs as a
non-root user and keeps its data in `/data`.

```bash
docker run --rm -p 8000:8000 -v omnirag-data:/data ghcr.io/manas-thakur/omnirag:latest
```

Then open `http://localhost:8000`. Pin a version with a tag such as `:0.3.0` or `:0.3`.
To build the image yourself from a checkout:

```bash
docker build -t omnirag .
docker run --rm -p 8000:8000 -v omnirag-data:/data omnirag
```

See [Deployment](/omnirag/docs/guides/deployment/) for API keys, CORS and seeding a
knowledge base inside the container.

## From source

```bash
git clone https://github.com/Manas-thakur/omnirag
cd omnirag
uv sync --extra server --extra pdf --extra images   # creates .venv with the dev tools
uv run omnirag --help
uv run pytest -q
```

The web app sources live in `web/` and are only needed if you want to change the interface;
see [Contributing](/omnirag/docs/contributing/).

## Where data lives

Knowledge bases are stored under `OMNIRAG_HOME` (default `~/.omnirag`), one directory per
knowledge base. Pass `--data-dir` / `-d` to any command, or set the variable, to use another
location. Removing a knowledge base never touches the source files it was built from.
