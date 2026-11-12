"""End-to-end showcase: ingest the multi-modal sample corpus and ask questions.

    uv run python examples/run_demo.py                 # offline, extractive answers
    uv run python examples/run_demo.py --llm ollama    # use a local Ollama model

The demo uses its own data directory (``examples/.data``) so it never touches
your real knowledge bases.
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
from pathlib import Path

from omnirag import IndexManager

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
DATA = HERE / ".data"

QUESTIONS = [
    # (question, what it demonstrates)
    ("How does the rate limiter work?", "code + docs"),
    ("What was decided about the database migration?", "audio transcript"),
    ("Show me the authentication flow diagram", "image description"),
    ("How much did the Redis cache improve p95 latency?", "table + transcript"),
    ("modality:code what happens when a token is expired?", "inline modality filter"),
    ("What should on-call do when p95 latency is high?", "HTML runbook"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", default="none", help="none | ollama[:model] | openai[:model]")
    parser.add_argument("--fresh", action="store_true", help="Delete the demo data dir first.")
    args = parser.parse_args()

    if args.fresh and DATA.exists():
        shutil.rmtree(DATA)

    manager = IndexManager(DATA)
    with manager.get_or_create("demo", description="OmniRAG multi-modal sample corpus") as kb:
        report = kb.ingest([CORPUS])
        stats = kb.stats()
        print(
            f"Ingested {CORPUS.relative_to(HERE.parent)}: {len(report.added)} added, "
            f"{len(report.updated)} updated, {len(report.unchanged)} unchanged, "
            f"{len(report.failed)} failed"
        )
        print(f"Knowledge base 'demo': {stats.documents} documents, {stats.chunks} chunks")
        print(
            "  by modality: " + ", ".join(f"{m}={n}" for m, n in sorted(stats.by_modality.items()))
        )

        for question, label in QUESTIONS:
            answer = kb.ask(question, llm=args.llm, k=4)
            print("\n" + "=" * 78)
            print(f"Q: {question}    [{label}]")
            print("-" * 78)
            print(answer.text)
            print("\nSources:")
            for src in answer.sources:
                mark = "*" if src.index in answer.cited else " "
                where = src.metadata.get("path", src.label)
                loc = f" ({src.location})" if src.location else ""
                print(f" {mark}[{src.index}] {src.modality:<5} {where}{loc}")
            for warning in answer.warnings:
                print(f"  warning: {warning}")
            print(f"({answer.backend}, {answer.timings['total_ms']:.0f} ms)")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
