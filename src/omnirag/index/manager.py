"""Manage named knowledge bases under a data directory.

Layout::

    $OMNIRAG_HOME/
      kbs/
        <name>/
          kb.json              configuration (embedder spec, chunking params)
          store.sqlite         documents, chunks, metadata, vectors
          embed_cache.sqlite   embedding cache
"""

from __future__ import annotations

import gc
import re
import shutil
from pathlib import Path

from omnirag.config import Settings
from omnirag.index.knowledge_base import KBConfig, KnowledgeBase, new_config

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class KnowledgeBaseError(Exception):
    pass


class IndexManager:
    def __init__(self, home: str | Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.home = Path(home).expanduser() if home else self.settings.home
        if home:
            self.settings = self.settings.with_overrides(home=self.home)
        self.root = self.home / "kbs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise KnowledgeBaseError(
                f"invalid knowledge base name {name!r}: use letters, digits, '.', '_' or '-'"
            )
        return self.root / name

    def exists(self, name: str) -> bool:
        return (self._path(name) / "kb.json").is_file()

    def create(
        self, name: str, description: str = "", embedder: str | None = None, exist_ok: bool = False
    ) -> KnowledgeBase:
        path = self._path(name)
        if (path / "kb.json").is_file():
            if exist_ok:
                return self.get(name)
            raise KnowledgeBaseError(f"knowledge base {name!r} already exists")
        path.mkdir(parents=True, exist_ok=True)
        new_config(name, description, embedder or self.settings.embedder, self.settings).save(
            path / "kb.json"
        )
        return KnowledgeBase(path, self.settings)

    def get(self, name: str) -> KnowledgeBase:
        path = self._path(name)
        if not (path / "kb.json").is_file():
            raise KnowledgeBaseError(
                f"knowledge base {name!r} does not exist (create it with: omnirag kb create {name})"
            )
        return KnowledgeBase(path, self.settings)

    def get_or_create(self, name: str, **kwargs) -> KnowledgeBase:
        return self.create(name, exist_ok=True, **kwargs)

    def list(self) -> list[KBConfig]:
        configs = []
        for p in sorted(self.root.iterdir()):
            cfg = p / "kb.json"
            if cfg.is_file():
                try:
                    configs.append(KBConfig.load(cfg))
                except (ValueError, TypeError):
                    continue
        return configs

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.exists():
            raise KnowledgeBaseError(f"knowledge base {name!r} does not exist")
        gc.collect()  # release any lingering SQLite handles (matters on Windows)
        shutil.rmtree(path)
