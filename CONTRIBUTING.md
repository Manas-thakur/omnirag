# Contributing to OmniRAG

Thanks for your interest in improving OmniRAG. Bug reports, documentation fixes, new ingestors
and retrieval improvements are all welcome.

## Ways to help

- **Report a bug:** open an issue with the command or request you ran, what you expected, what
  happened, and the output of `omnirag doctor --json`.
- **Suggest a feature:** open an issue describing the problem first; the roadmap in the README
  lists what is already planned.
- **Send a pull request:** small, focused changes are easiest to review. For larger changes,
  open an issue first so we can agree on the approach.

## Repository layout

| Path                         | What it is                                                         |
| ---------------------------- | ------------------------------------------------------------------ |
| `src/omnirag/`               | the Python package: ingestion, chunking, embeddings, store, retrieval, generation, CLI and server |
| `src/omnirag/server/static/` | the **built** web app (generated; do not edit by hand)             |
| `web/`                       | web app sources: Vite, React, TypeScript, Tailwind CSS, shadcn/ui  |
| `site/`                      | landing page and documentation (Astro + Starlight)                 |
| `tests/`                     | pytest suite (offline: no network, no model downloads)             |
| `examples/corpus/`           | the sample corpus used by the demo, tests and screenshots          |
| `scripts/`                   | maintenance scripts, such as the CLI reference generator           |
| `docs/`                      | design notes and screenshots                                       |

## Python

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Manas-thakur/omnirag
cd omnirag
uv sync --extra server --extra pdf --extra images
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

`make demo` ingests the sample corpus and runs a few queries; `make serve` starts the web app on
it. Tests must stay offline: mock model servers instead of calling them.

## Web app

You need Node.js 20+ and pnpm 10.

```bash
cd web
pnpm install
pnpm dev          # http://localhost:8752, proxies /api to http://127.0.0.1:8751
```

Run the API next to it, for example
`uv run omnirag serve --port 8751 --kb demo` (set `OMNIRAG_API` to point the dev server
elsewhere). Before committing a change to `web/`:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm build        # writes src/omnirag/server/static/
```

**Commit the build output together with the source change.** CI rebuilds the app and fails if
`src/omnirag/server/static/` differs from what is committed, because that folder is what
`pip install` ships.

UI primitives in `web/src/components/ui/` come from shadcn/ui (`pnpm dlx shadcn@latest add
<name>`); app components live in `web/src/components/app/`, the API client, stream parser and
state in `web/src/lib/`.

## Documentation site

```bash
cd site
pnpm install
pnpm dev          # http://localhost:8755/omnirag/
pnpm build        # also checks internal links
```

Docs pages are Markdown in `site/src/content/docs/docs/`. The CLI reference is generated from
the CLI itself; after changing a command or option, run:

```bash
uv run python scripts/gen_cli_docs.py
```

Screenshots in `docs/screenshots/` are real captures of the web app on the sample corpus.

## Style

- Python: formatted and linted with ruff (line length 100). Type hints on public functions.
- TypeScript: strict mode, ESLint, components in function style.
- Keep modules small and readable; OmniRAG deliberately implements its retrieval pipeline
  without large frameworks.
- Update `CHANGELOG.md` under *Unreleased* for user-visible changes, and the docs when behaviour
  changes.

## Releases

Maintainers bump the version in `pyproject.toml`, `src/omnirag/__init__.py` and
`web/package.json`, run `uv lock`, move the *Unreleased* notes to a new version in
`CHANGELOG.md`, and push a `vX.Y.Z` tag. The release workflow (`.github/workflows/release.yml`)
checks that the tag matches all three versions, builds the web app, runs the tests, builds and
smoke-tests the sdist and wheel, creates a GitHub Release with the matching changelog section,
and pushes a linux/amd64 + linux/arm64 image to `ghcr.io/manas-thakur/omnirag`. Tags containing
`-` (such as `v0.4.0-rc1`) are marked as pre-releases.

Publishing to PyPI uses trusted publishing and stays off until the repository variable
`PYPI_PUBLISH` is `true`. One-time setup: on PyPI add a pending trusted publisher for project
`omnirag` (owner `Manas-thakur`, repository `omnirag`, workflow `release.yml`, environment
`pypi`), create a GitHub environment named `pypi`, then set the variable. After the first image
push, make the ghcr.io package public if it should be pullable without logging in.

The documentation site is deployed by `.github/workflows/pages.yml` on pushes to `main` that
touch `site/` or `docs/` (Settings → Pages → Source: GitHub Actions).

## License

By contributing you agree that your contributions are licensed under the
[MIT License](https://github.com/Manas-thakur/omnirag/blob/main/LICENSE).
