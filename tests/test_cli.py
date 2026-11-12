from __future__ import annotations

import json

from typer.testing import CliRunner

from omnirag.cli import app

runner = CliRunner()


def run(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_version():
    assert "omnirag" in run("--version")


def test_full_cli_workflow(tmp_path, corpus):
    home = str(tmp_path / "cli-home")
    assert "Created knowledge base" in run("--data-dir", home, "kb", "create", "demo")
    out = run("--data-dir", home, "ingest", str(corpus), "--kb", "demo")
    assert "10 added" in out

    again = run("--data-dir", home, "ingest", str(corpus), "--kb", "demo", "-q")
    assert "10 unchanged" in again

    stats = json.loads(run("--data-dir", home, "stats", "--kb", "demo", "--json"))
    assert stats["documents"] == 10

    answer = json.loads(
        run(
            "--data-dir",
            home,
            "query",
            "How does the token bucket refill?",
            "--kb",
            "demo",
            "--llm",
            "none",
            "--json",
        )
    )
    assert answer["backend"] == "extractive"
    assert answer["cited"]
    assert "[" in answer["answer"]

    text = run("--data-dir", home, "query", "what was decided in the meeting", "--kb", "demo")
    assert "extractive" in text

    hits = json.loads(
        run("--data-dir", home, "search", "p95 latency", "--kb", "demo", "-m", "table", "--json")
    )
    assert hits and all(h["modality"] == "table" for h in hits)

    assert "demo" in run("--data-dir", home, "kb", "list")
    assert "Re-embedded" in run("--data-dir", home, "kb", "rebuild", "demo")
    assert "Removed 0" in run("--data-dir", home, "kb", "prune", "demo")
    assert "Deleted" in run("--data-dir", home, "kb", "delete", "demo", "--yes")


def test_ingest_auto_creates_kb(tmp_path, corpus):
    home = str(tmp_path / "h")
    out = run("--data-dir", home, "ingest", str(corpus / "docs"), "--kb", "auto")
    assert "Created knowledge base auto" in out


def test_errors_exit_nonzero(tmp_path):
    home = str(tmp_path / "h")
    result = runner.invoke(app, ["--data-dir", home, "query", "x", "--kb", "nope"])
    assert result.exit_code == 1
    result = runner.invoke(
        app, ["--data-dir", home, "ingest", str(tmp_path / "missing"), "--kb", "k"]
    )
    assert result.exit_code == 1
    result = runner.invoke(app, ["--data-dir", home, "kb", "create", "bad name!"])
    assert result.exit_code == 1
