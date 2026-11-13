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
import os
import re
import shutil
import uuid
import weakref
from pathlib import Path

from omnirag.config import ConfigError, Settings
from omnirag.embed import EmbeddingError
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
        # Knowledge bases opened through this manager, closed before a delete.
        self._open: weakref.WeakSet[KnowledgeBase] = weakref.WeakSet()

    def _open_kb(self, path: Path) -> KnowledgeBase:
        kb = KnowledgeBase(path, self.settings)
        self._open.add(kb)
        return kb

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
        try:
            config = new_config(
                name, description, embedder or self.settings.embedder, self.settings
            )
        except (EmbeddingError, ConfigError) as exc:
            raise KnowledgeBaseError(str(exc)) from exc
        path.mkdir(parents=True, exist_ok=True)
        config.save(path / "kb.json")
        return self._open_kb(path)

    def get(self, name: str) -> KnowledgeBase:
        path = self._path(name)
        if not (path / "kb.json").is_file():
            raise KnowledgeBaseError(
                f"knowledge base {name!r} does not exist (create it with: omnirag kb create {name})"
            )
        return self._open_kb(path)

    def get_or_create(self, name: str, **kwargs) -> KnowledgeBase:
        return self.create(name, exist_ok=True, **kwargs)

    def list(self) -> list[KBConfig]:
        configs = []
        for p in sorted(self.root.iterdir()):
            if p.name.startswith("."):
                continue  # e.g. a knowledge base that is being deleted
            cfg = p / "kb.json"
            if cfg.is_file():
                try:
                    configs.append(KBConfig.load(cfg))
                except (ValueError, TypeError):
                    continue
        return configs

    def delete(self, name: str) -> None:
        """Delete a knowledge base directory.

        Knowledge bases this manager opened are closed first. The directory is
        renamed before it is removed, so a file held open by another process
        (e.g. a running server on Windows) leaves the knowledge base intact and
        raises :class:`KnowledgeBaseError` instead of half-deleting it.
        """
        path = self._path(name)
        if not path.exists():
            raise KnowledgeBaseError(f"knowledge base {name!r} does not exist")
        target = path.resolve()
        for kb in list(self._open):
            if kb.path.resolve() == target:
                kb.close()
        gc.collect()  # release any lingering SQLite handles (matters on Windows)
        trash = self.root / f".{name}.deleting-{uuid.uuid4().hex[:8]}"
        try:
            os.replace(path, trash)
        except PermissionError as exc:
            raise KnowledgeBaseError(
                f"could not delete knowledge base {name!r}: its files are in use by another "
                "program (for example a running 'omnirag serve'). Stop it and try again."
            ) from exc
        shutil.rmtree(trash, ignore_errors=True)
