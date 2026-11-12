from __future__ import annotations

import pytest

from omnirag import IndexManager, KnowledgeBaseError
from omnirag.config import Settings
from omnirag.store.models import Modality


def test_create_list_get_delete(manager):
    kb = manager.create("notes", description="my notes")
    assert kb.config.embedder == "hashing:2048"
    kb.close()
    assert [c.name for c in manager.list()] == ["notes"]
    with pytest.raises(KnowledgeBaseError):
        manager.create("notes")
    manager.create("notes", exist_ok=True).close()
    with pytest.raises(KnowledgeBaseError):
        manager.get("missing")
    with pytest.raises(KnowledgeBaseError):
        manager.create("../escape")
    manager.delete("notes")
    assert manager.list() == []
    assert not manager.exists("notes")


def test_ingest_whole_corpus(demo_kb):
    stats = demo_kb.stats()
    assert stats.documents == 10
    assert set(stats.documents_by_modality) == {m.value for m in Modality}
    assert stats.chunks >= 20
    assert stats.dimension == 2048


def test_incremental_ingest(manager, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    a = folder / "a.md"
    b = folder / "b.md"
    a.write_text("# A\nAlpha content about apples.")
    b.write_text("# B\nBeta content about bananas.")
    with manager.create("inc") as kb:
        first = kb.ingest([folder])
        assert len(first.added) == 2 and first.chunks == 2
        second = kb.ingest([folder])
        assert second.processed == 0 and len(second.unchanged) == 2

        b.write_text("# B\nBeta content about blueberries now.")
        third = kb.ingest([folder])
        assert third.updated == [str(b.resolve())] and len(third.unchanged) == 1
        assert "blueberries" in kb.ask("blueberries").text

        forced = kb.ingest([folder], force=True)
        assert len(forced.updated) == 2

        a.unlink()
        assert kb.prune() == [str(a.resolve())]
        assert kb.stats().documents == 1
        assert kb.remove(b)
        assert kb.stats().documents == 0
        assert not kb.remove(b)


def test_failed_files_are_reported(manager, tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{nope")
    with manager.create("bad") as kb:
        report = kb.ingest([bad])
    assert str(bad.resolve()) in report.failed


def test_ask_returns_cited_answer(demo_kb):
    answer = demo_kb.ask("What was decided about the database migration?", llm="none")
    assert answer.backend == "extractive"
    assert answer.cited
    assert any(s.modality == "audio" for s in answer.cited_sources)
    assert answer.query["intent"]
    assert answer.timings["total_ms"] >= answer.timings["retrieve_ms"]


def test_ask_with_custom_llm_object(demo_kb):
    from omnirag.generate.llm import LLM

    class Echo(LLM):
        name = "echo"

        def complete(self, messages, temperature=0.1, max_tokens=800):
            return "The limiter uses a token bucket [1]."

    answer = demo_kb.ask("how does rate limiting work", llm=Echo())
    assert answer.backend == "echo" and answer.cited == [1]


def test_unreachable_llm_falls_back(demo_kb, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    demo_kb.settings = Settings.from_env()
    answer = demo_kb.ask("how does rate limiting work", llm="ollama")
    assert answer.backend == "extractive"
    assert answer.warnings


def test_rebuild_with_new_embedder(demo_kb):
    n = demo_kb.rebuild("hashing:512")
    assert n == demo_kb.stats().chunks
    assert demo_kb.stats().dimension == 512
    assert demo_kb.config.embedder == "hashing:512"
    assert demo_kb.search("token bucket", k=1).results


def test_manager_uses_env_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIRAG_HOME", str(tmp_path / "envhome"))
    mgr = IndexManager()
    assert mgr.root == tmp_path / "envhome" / "kbs"
