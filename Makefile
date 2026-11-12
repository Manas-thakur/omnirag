.PHONY: install test lint format demo demo-cli serve docker clean

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
