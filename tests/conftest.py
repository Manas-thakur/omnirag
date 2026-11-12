from __future__ import annotations

from pathlib import Path

import pytest

from omnirag.config import Settings
from omnirag.index import IndexManager

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "corpus"

_ENV_VARS = [
    "OMNIRAG_HOME",
    "OMNIRAG_EMBEDDER",
    "OMNIRAG_LLM",
    "OMNIRAG_KB",
    "OMNIRAG_VLM_MODEL",
    "OMNIRAG_WHISPER_MODEL",
    "OMNIRAG_CHUNK_SIZE",
    "OMNIRAG_CHUNK_OVERLAP",
    "OLLAMA_HOST",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
]


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Never touch the user's real data dir or reach a real model server."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMNIRAG_HOME", str(tmp_path / "omnirag-home"))


@pytest.fixture
def corpus() -> Path:
    return CORPUS


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(home=tmp_path / "home")


@pytest.fixture
def manager(tmp_path, settings) -> IndexManager:
    return IndexManager(tmp_path / "home", settings)


@pytest.fixture
def demo_kb(manager, corpus):
    kb = manager.create("demo")
    kb.ingest([corpus])
    yield kb
    kb.close()
