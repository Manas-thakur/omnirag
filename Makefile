.PHONY: install test lint format demo demo-cli serve docker clean web web-dev site site-dev docs-cli

install:  ## Create the virtualenv with dev, server, pdf and image extras
	uv sync --extra server --extra pdf --extra images

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check . --fix

demo:  ## Ingest examples/corpus and run sample queries (offline)
	uv run python examples/run_demo.py

demo-cli:
	bash examples/demo.sh

serve: demo  ## Start the web UI on the demo knowledge base
	OMNIRAG_HOME=examples/.data uv run omnirag serve --kb demo

docker:
	docker build -t omnirag .

clean:
	rm -rf examples/.data .pytest_cache .ruff_cache dist build

web:  ## Type-check, lint, test and build the web app into src/omnirag/server/static
	cd web && pnpm install && pnpm typecheck && pnpm lint && pnpm test && pnpm build

web-dev:  ## Vite dev server on :8752 (proxies /api to :8751)
	cd web && pnpm dev

site:  ## Build the landing page and docs into site/dist
	cd site && pnpm install && pnpm build

site-dev:
	cd site && pnpm dev

docs-cli:  ## Regenerate the CLI reference page from the CLI
	uv run python scripts/gen_cli_docs.py
