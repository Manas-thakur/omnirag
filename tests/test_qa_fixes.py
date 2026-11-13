"""Regressions from the hands-on QA pass of v0.3.0 (ingest, embedders, CLI, HTTP)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from omnirag.cli import app
from omnirag.config import ConfigError, Settings, install_hint
from omnirag.embed import EmbeddingError
from omnirag.index import IndexManager, KnowledgeBaseError
from omnirag.ingest.base import IngestContext
from omnirag.ingest.orchestrator import discover
from omnirag.ingest.table import TableIngestor

runner = CliRunner()
HAS_ST = importlib.util.find_spec("sentence_transformers") is not None


class _Result:
    def __init__(self, result) -> None:
        self.exit_code = result.exit_code
        self.exception = result.exception
        # Rich wraps long lines at the terminal width: compare unwrapped text.
        self.output = " ".join(result.output.split())


def cli(*args: str, env: dict[str, str] | None = None) -> _Result:
    return _Result(runner.invoke(app, list(args), env=env))


# ------------------------------------------------------------------ tables
def test_table_rows_keep_values_exactly_as_written(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(
        "order,amount,discount\nA1,3035.34,0.5\nA2,1999999.99,0.25\nA3,3035.340,0.125\n",
        encoding="utf-8",
    )
    doc = TableIngestor().ingest(path, IngestContext(root=tmp_path))
    summary, rows = doc.chunks[0].content, doc.chunks[1].content
    assert "amount=3035.34," in rows and "amount=1999999.99," in rows
    assert "amount=3035.340" in rows  # not normalised either
    assert "e+" not in rows and "e+" not in summary
    assert "max 1999999.99" in summary and "min 3035.34" in summary
    # Statistics are rounded for reading but never written in scientific notation.
    assert "mean 668690.22" in summary


def test_json_table_numbers_are_not_rounded(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps([{"sku": "x", "price": 1234567.891}]), encoding="utf-8")
    doc = TableIngestor().ingest(path, IngestContext(root=tmp_path))
    assert "price=1234567.891" in doc.chunks[1].content


# --------------------------------------------------------------- embedders
@pytest.mark.parametrize("spec", ["bogus:3", "hashing:abc", "hashing:0", "st:", "ollama:"])
def test_invalid_embedder_spec_is_rejected_at_creation(manager, spec):
    with pytest.raises(KnowledgeBaseError):
        manager.create("kb", embedder=spec)
    assert not (manager.root / "kb").exists()


@pytest.mark.skipif(HAS_ST, reason="sentence-transformers is installed")
def test_st_embedder_without_extra_is_rejected_with_github_install_hint(tmp_path):
    result = cli("--data-dir", str(tmp_path / "h"), "kb", "create", "kb", "-e", "st:some/model")
    assert result.exit_code == 1
    # Rich markup must not eat the [embeddings] extra.
    assert "omnirag[embeddings] @ git+https://github.com/Manas-thakur/omnirag" in result.output
    assert "Traceback" not in result.output


def test_cli_create_rejects_bogus_embedder(tmp_path):
    result = cli("--data-dir", str(tmp_path / "h"), "kb", "create", "kb", "-e", "bogus:3")
    assert result.exit_code == 1
    assert "unknown embedder spec 'bogus:3'" in result.output


def test_rebuild_with_bad_embedder_keeps_the_old_one(demo_kb):
    before = demo_kb.config.embedder
    hits = demo_kb.search("token bucket", k=3).results
    for spec in ("bogus:1", "hashing:abc", "st:"):
        with pytest.raises(EmbeddingError):
            demo_kb.rebuild(spec)
    saved = json.loads((demo_kb.path / "kb.json").read_text(encoding="utf-8"))
    assert saved["embedder"] == before == demo_kb.config.embedder
    assert [r.chunk.chunk_id for r in demo_kb.search("token bucket", k=3).results] == [
        r.chunk.chunk_id for r in hits
    ]


def test_rebuild_with_unreachable_model_server_keeps_config(demo_kb):
    settings = demo_kb.settings.with_overrides(ollama_host="http://127.0.0.1:9", request_timeout=2)
    demo_kb.settings = settings
    with pytest.raises(EmbeddingError):
        demo_kb.rebuild("ollama:nomic-embed-text")
    assert demo_kb.config.embedder == "hashing:2048"
    assert demo_kb.search("token bucket", k=1).results


def test_cli_rebuild_bad_embedder_is_a_clean_error(tmp_path, corpus):
    home = str(tmp_path / "h")
    assert cli("--data-dir", home, "ingest", str(corpus / "docs"), "--kb", "k").exit_code == 0
    result = cli("--data-dir", home, "kb", "rebuild", "k", "-e", "bogus:3")
    assert result.exit_code == 1
    assert "previous embedder" in result.output and "Traceback" not in result.output
    assert cli("--data-dir", home, "query", "token", "--kb", "k").exit_code == 0


# ------------------------------------------------------------------ ingest
def test_ingest_never_reads_the_data_dir(tmp_path):
    docs = tmp_path / "project"
    docs.mkdir()
    (docs / "notes.md").write_text("# Notes\n\nThe deploy runs nightly.", encoding="utf-8")
    home = docs / "omnirag-home"  # a data dir inside the folder being ingested
    mgr = IndexManager(home, Settings(home=home))
    kb = mgr.create("k")
    (kb.path / "uploads").mkdir()
    (kb.path / "uploads" / "up.md").write_text("uploaded", encoding="utf-8")
    report = kb.ingest([docs])
    assert [Path(s).name for s in report.added] == ["notes.md"]
    # Explicitly named files inside the data dir are refused and reported.
    report = kb.ingest([kb.path / "kb.json"])
    assert not report.added and "data directory" in next(iter(report.skipped.values()))
    # ...except the knowledge base's own uploads.
    assert kb.ingest([kb.uploads_dir / "up.md"]).added
    kb.close()


def test_discover_rejects_blank_paths_and_reports_unsupported(tmp_path):
    with pytest.raises(ValueError, match="empty path"):
        discover([""])
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    skipped: dict[str, str] = {}
    assert discover([exe], skipped=skipped) == []
    assert "unsupported file type" in skipped[str(exe.resolve())]


def test_folder_walk_does_not_follow_links_outside(tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "keys.md").write_text("secret", encoding="utf-8")
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("hello", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        (root / "keys-link.md").symlink_to(outside / "keys.md")
    except OSError:
        if os.name != "nt":
            pytest.skip("creating symlinks is not permitted here")
        import _winapi  # Windows without symlink rights: a directory junction

        _winapi.CreateJunction(str(outside), str(root / "linked"))
    skipped: dict[str, str] = {}
    found = discover([root], skipped=skipped)
    assert [f.name for f in found] == ["a.md"]
    assert any("outside" in reason for reason in skipped.values())


def test_cli_ingest_warns_about_unsupported_and_empty(tmp_path):
    home = str(tmp_path / "h")
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    result = cli("--data-dir", home, "ingest", str(exe), "--kb", "k")
    assert result.exit_code == 1 and "unsupported file type" in result.output
    empty = tmp_path / "empty"
    empty.mkdir()
    result = cli("--data-dir", home, "ingest", str(empty), "--kb", "k")
    assert result.exit_code == 0 and "no supported files found" in result.output
    result = cli("--data-dir", home, "ingest", "", "--kb", "k")
    assert result.exit_code == 1 and "empty path" in result.output


# ------------------------------------------------------------------- CLI
def test_bad_environment_settings_are_clean_errors(tmp_path):
    home = str(tmp_path / "h")
    result = cli("--data-dir", home, "kb", "list", env={"OMNIRAG_CHUNK_SIZE": "abc"})
    assert result.exit_code == 1 and "OMNIRAG_CHUNK_SIZE must be a number" in result.output
    result = cli(
        "--data-dir",
        home,
        "kb",
        "list",
        env={"OMNIRAG_CHUNK_SIZE": "200", "OMNIRAG_CHUNK_OVERLAP": "200"},
    )
    assert result.exit_code == 1 and "must be smaller than the chunk size" in result.output
    assert not isinstance(result.exception, ConfigError)  # handled, not a traceback


def test_serve_validates_port_and_warns_about_missing_kb(tmp_path, monkeypatch):
    pytest.importorskip("uvicorn")
    result = cli("--data-dir", str(tmp_path / "h"), "serve", "--port", "99999")
    assert result.exit_code == 2 and "Traceback" not in result.output
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    result = cli("--data-dir", str(tmp_path / "h"), "serve", "--kb", "nothere", "--port", "8851")
    assert result.exit_code == 0 and "'nothere' does not exist yet" in result.output


def test_search_without_results_says_so(tmp_path, corpus):
    home = str(tmp_path / "h")
    cli("--data-dir", home, "ingest", str(corpus / "docs"), "--kb", "k")
    result = cli("--data-dir", home, "search", "zzzqqqxx", "--kb", "k", "--mode", "bm25")
    assert result.exit_code == 0 and "No results" in result.output


def test_query_warnings_and_strict_inline_modality(tmp_path, corpus):
    home = str(tmp_path / "h")
    cli("--data-dir", home, "ingest", str(corpus / "docs"), "--kb", "k")
    result = cli("--data-dir", home, "query", "token refill", "--kb", "k", "--hyde")
    assert result.exit_code == 0 and "HyDE query expansion needs an LLM" in result.output
    result = cli("--data-dir", home, "query", "modality:bogus token", "--kb", "k")
    assert result.exit_code == 1 and "unknown modality 'bogus'" in result.output
    result = cli("--data-dir", home, "query", "token", "--kb", "k", "--llm", "openai")
    assert result.exit_code == 1 and "OPENAI_API_KEY is not set" in result.output


def test_sources_are_listed_in_relevance_order(demo_kb):
    for q in ("How are refresh tokens rotated?", "p95 latency", "what was decided"):
        scores = [s.score for s in demo_kb.ask(q, k=6).sources]
        assert scores == sorted(scores, reverse=True), q


def test_delete_closes_open_handles_in_process(manager, corpus):
    kb = manager.create("busy")
    kb.ingest([corpus / "docs"])
    kb.search("token")  # opens the store and the embedding cache
    manager.delete("busy")  # must not fail with WinError 32
    assert not manager.exists("busy")


@pytest.mark.skipif(os.name != "nt", reason="open files only block deletion on Windows")
def test_delete_of_kb_held_by_another_process_is_a_clean_error(tmp_path, corpus):
    home = tmp_path / "home"
    other = IndexManager(home, Settings(home=home))  # stands in for a running server
    held = other.create("busy")
    held.ingest([corpus / "docs"])
    with pytest.raises(KnowledgeBaseError, match="in use by another program"):
        IndexManager(home, Settings(home=home)).delete("busy")
    assert other.exists("busy") and held.store.count_chunks()
    held.close()


def test_install_hint_points_at_github():
    assert install_hint("server") == (
        'pip install "omnirag[server] @ git+https://github.com/Manas-thakur/omnirag"'
    )


# ------------------------------------------------------------------ HTTP
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient  # noqa: E402

from omnirag.server.app import create_app  # noqa: E402


@pytest.fixture
def http(tmp_path, settings):
    with TestClient(create_app(home=tmp_path / "srv", default_kb="demo", settings=settings)) as c:
        yield c


def test_http_create_kb_validates_embedder(http):
    for spec in ("bogus:3", "hashing:abc", "st:"):
        r = http.post("/api/kbs", json={"name": "x", "embedder": spec})
        assert r.status_code == 400 and r.json()["detail"], spec
    assert http.get("/api/kbs").json() == []


def test_http_unexpected_errors_are_json(tmp_path, settings, monkeypatch):
    application = create_app(home=tmp_path / "srv", default_kb="demo", settings=settings)
    with TestClient(application, raise_server_exceptions=False) as c:
        c.post("/api/kbs", json={"name": "demo"})
        from omnirag.index.knowledge_base import KnowledgeBase

        def boom(self):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(KnowledgeBase, "stats", boom)
        r = c.get("/api/kbs/demo/stats")
        assert r.status_code == 500
        assert r.headers["content-type"].startswith("application/json")
        assert "RuntimeError" in r.json()["detail"]


def test_http_ingest_rejects_blank_paths_outside_roots_and_data_dir(http, tmp_path):
    assert http.post("/api/ingest", json={"paths": [""]}).status_code == 400
    assert http.post("/api/ingest", json={"paths": ["   "]}).status_code == 400
    outside = Path(tmp_path.anchor) / "definitely-not-allowed"
    assert http.post("/api/ingest", json={"paths": [str(outside)]}).status_code == 403
    # The data dir (inside an allowed root here) is never indexed.
    http.post("/api/kbs", json={"name": "demo"})
    r = http.post("/api/ingest", json={"paths": [str(tmp_path / "srv")]})
    assert r.status_code == 200 and r.json()["processed"] == 0


def test_http_failed_upload_leaves_no_file_and_batches_are_per_file(http):
    http.post("/api/kbs", json={"name": "up"})
    kb_dir = Path(http.get("/api/kbs/up/stats").json()["path"])
    r = http.post(
        "/api/kbs/up/upload",
        files=[
            ("files", ("broken.json", b"{not json", "application/json")),
            ("files", ("setup.exe", b"MZ", "application/octet-stream")),
            ("files", ("config.yaml", b"retries: 3\ntimeout: 30s\n", "application/yaml")),
        ],
    )
    assert r.status_code == 200, r.text
    files = {f["name"]: f for f in r.json()["files"]}
    assert files["broken.json"]["status"] == "failed" and files["broken.json"]["error"]
    assert files["setup.exe"]["status"] == "rejected"
    assert files["config.yaml"]["status"] == "added"
    assert sorted(p.name for p in (kb_dir / "uploads").iterdir()) == ["config.yaml"]


def test_http_small_contract_fixes(http, tmp_path):
    assert http.head("/").status_code == 200
    http.post("/api/kbs", json={"name": "demo"})
    doc = tmp_path / "gone.md"
    doc.write_text("# Gone\n\nThis file will be deleted after ingest.", encoding="utf-8")
    http.post("/api/ingest", json={"paths": [str(doc)]})
    d = http.get("/api/kbs/demo/documents").json()[0]
    chunk_id = f"{d['doc_id']}-0000"
    assert http.get(f"/api/kbs/demo/chunks/{chunk_id}", params={"window": 3}).status_code == 200
    for bad in (-1, 4, 99):
        assert (
            http.get(f"/api/kbs/demo/chunks/{chunk_id}", params={"window": bad}).status_code == 422
        )
    doc.unlink()
    raw = http.get(f"/api/kbs/demo/documents/{d['doc_id']}/raw")
    assert raw.status_code == 410 and "no longer exists" in raw.json()["detail"]

    full = {"llm": "ollama", "model": "qwen2.5:7b", "base_url": "http://gpu:11434", "top_k": 8}
    assert http.put("/api/kbs/demo/settings", json=full).json() == full
    assert http.put("/api/kbs/demo/settings", json={"top_k": 3}).json() == {**full, "top_k": 3}
    assert http.get("/api/kbs/demo/settings").json()["model"] == "qwen2.5:7b"


def test_http_raw_media_types_match_the_docs(http, corpus):
    http.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})
    docs = {d["name"]: d["doc_id"] for d in http.get("/api/kbs/demo/documents").json()}
    csv = http.get(f"/api/kbs/demo/documents/{docs['latency_benchmarks.csv']}/raw")
    assert csv.headers["content-type"].startswith("text/plain")  # on every platform
    svg = http.get(f"/api/kbs/demo/documents/{docs['auth-flow.svg']}/raw")
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in svg.headers["content-security-policy"]


def test_rebuild_repairs_a_kb_whose_saved_embedder_is_broken(demo_kb):
    # A knowledge base broken by the old rebuild bug (spec saved before it was checked).
    demo_kb.config.embedder = "bogus:3"
    demo_kb.config.save(demo_kb.path / "kb.json")
    demo_kb._embedder = None
    assert demo_kb.rebuild("hashing:1024") > 0
    assert demo_kb.config.embedder == "hashing:1024"
    assert demo_kb.search("token bucket", k=1).results
