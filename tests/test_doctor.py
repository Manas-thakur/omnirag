"""``omnirag doctor`` and the model-server probes behind it and /api/status."""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from omnirag import health
from omnirag.cli import app
from omnirag.config import Settings
from omnirag.doctor import FAIL, OK, WARN, run_checks
from omnirag.health import probe_llm, probe_ollama, probe_openai

runner = CliRunner()


@pytest.fixture
def mock_http(monkeypatch):
    """Route the probes' httpx clients through a handler set by the test."""
    state = {"handler": lambda request: httpx.Response(404)}
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda r: state["handler"](r))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(health.httpx, "Client", factory)
    return state


def test_probe_ollama(mock_http):
    mock_http["handler"] = lambda r: httpx.Response(
        200, json={"models": [{"name": "llama3.1:8b"}, {"name": "nomic-embed-text:latest"}]}
    )
    p = probe_ollama("localhost:11434")
    assert p.reachable and p.url == "http://localhost:11434"
    assert p.models == ["llama3.1:8b", "nomic-embed-text:latest"]

    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    mock_http["handler"] = refuse
    down = probe_ollama("http://localhost:11434")
    assert not down.reachable and "refused" in down.detail


def test_probe_openai(mock_http):
    seen = {}

    def ok(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "gpt-x"}]})

    mock_http["handler"] = ok
    p = probe_openai("http://api/v1/", "sk-1")
    assert p.reachable and p.models == ["gpt-x"] and seen["auth"] == "Bearer sk-1"

    mock_http["handler"] = lambda r: httpx.Response(401)
    assert "rejected" in probe_openai("http://api/v1", "bad").detail
    assert "needed" in probe_openai("http://api/v1").detail
    mock_http["handler"] = lambda r: httpx.Response(500)
    assert probe_openai("http://api/v1").reachable  # up, but /models failed


def test_probe_llm_dispatch(mock_http):
    mock_http["handler"] = lambda r: httpx.Response(200, json={"models": []})
    settings = Settings(ollama_host="http://ollama:11434")
    assert probe_llm("none", settings) is None
    assert probe_llm("ollama:qwen", settings).name == "ollama"
    assert probe_llm("openai", settings).name == "openai"


def test_run_checks_offline(tmp_path):
    checks = run_checks(Settings(home=tmp_path / "data"), network=False)
    by_name = {c.name: c for c in checks}
    assert by_name["python"].status == OK
    assert by_name["data dir"].status == OK and "will be created" in by_name["data dir"].detail
    assert not (tmp_path / "data").exists()  # doctor never creates anything
    assert by_name["embedder"].status == OK
    assert by_name["extra: server"].status == OK
    assert by_name["ollama"].detail.startswith("skipped")
    assert not [c for c in checks if c.status == FAIL]


def test_run_checks_flags_problems(tmp_path, mock_http):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    mock_http["handler"] = refuse
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    settings = Settings(home=not_a_dir, embedder="st:some/model", llm="ollama")
    by_name = {c.name: c for c in run_checks(settings)}
    assert by_name["data dir"].status == FAIL
    assert by_name["ollama"].status == FAIL  # selected as the LLM but unreachable
    if by_name["extra: embeddings"].status != OK:
        assert by_name["embedder"].status == FAIL

    optional = {c.name: c for c in run_checks(Settings(home=tmp_path / "ok"))}
    assert optional["ollama"].status == WARN  # not selected: only a warning
    assert optional["openai"].detail.startswith("not configured")


def test_run_checks_reports_missing_ollama_model(tmp_path, mock_http):
    mock_http["handler"] = lambda r: httpx.Response(200, json={"models": [{"name": "phi3:latest"}]})
    by_name = {c.name: c for c in run_checks(Settings(home=tmp_path, llm="ollama:qwen2.5:7b"))}
    assert by_name["ollama"].status == WARN and "not pulled" in by_name["ollama"].detail
    ok = {c.name: c for c in run_checks(Settings(home=tmp_path, llm="ollama:phi3"))}
    assert ok["ollama"].status == OK


def test_doctor_cli(tmp_path, monkeypatch):
    result = runner.invoke(app, ["--data-dir", str(tmp_path), "doctor", "--no-network", "--json"])
    assert result.exit_code == 0, result.output
    checks = json.loads(result.output)
    assert {c["name"] for c in checks} >= {"python", "data dir", "embedder", "extra: server"}

    text = runner.invoke(app, ["--data-dir", str(tmp_path), "doctor", "--no-network"])
    assert text.exit_code == 0 and "All good" in text.output
    assert "omnirag[audio]" in text.output or "installed - local audio" in text.output

    monkeypatch.setenv("OMNIRAG_EMBEDDER", "bogus:thing")
    failing = runner.invoke(app, ["--data-dir", str(tmp_path), "doctor", "--no-network"])
    assert failing.exit_code == 1 and "problem" in failing.output
