"""Runtime configuration, resolved from environment variables.

Every setting has a sensible offline default so OmniRAG works out of the box
without any model server. Remote backends (Ollama, OpenAI-compatible APIs) are
only contacted when explicitly selected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def default_home() -> Path:
    """Directory where knowledge bases are stored (``OMNIRAG_HOME``)."""
    return Path(_env("OMNIRAG_HOME") or Path.home() / ".omnirag").expanduser()


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings.

    Use :meth:`Settings.from_env` to build one from the environment, and
    :meth:`Settings.with_overrides` to tweak individual fields.
    """

    home: Path = field(default_factory=default_home)
    embedder: str = "hashing"
    llm: str = "none"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    vlm_model: str | None = None
    whisper_model: str | None = None
    request_timeout: float = 120.0
    chunk_size: int = 1200
    chunk_overlap: int = 150
    # HTTP server
    api_key: str | None = None
    cors_origins: tuple[str, ...] = ()
    max_upload_mb: float = 50.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            home=default_home(),
            embedder=_env("OMNIRAG_EMBEDDER", "hashing") or "hashing",
            llm=(_env("OMNIRAG_LLM", "none") or "none").lower(),
            ollama_host=(_env("OLLAMA_HOST", "http://localhost:11434") or "").rstrip("/"),
            ollama_model=_env("OMNIRAG_OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b",
            openai_base_url=(_env("OPENAI_BASE_URL", "https://api.openai.com/v1") or "").rstrip(
                "/"
            ),
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OMNIRAG_OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
            vlm_model=_env("OMNIRAG_VLM_MODEL"),
            whisper_model=_env("OMNIRAG_WHISPER_MODEL"),
            request_timeout=float(_env("OMNIRAG_TIMEOUT", "120") or 120),
            chunk_size=int(_env("OMNIRAG_CHUNK_SIZE", "1200") or 1200),
            chunk_overlap=int(_env("OMNIRAG_CHUNK_OVERLAP", "150") or 150),
            api_key=_env("OMNIRAG_API_KEY"),
            cors_origins=tuple(
                o.strip().rstrip("/")
                for o in (_env("OMNIRAG_CORS_ORIGINS", "") or "").split(",")
                if o.strip()
            ),
            max_upload_mb=float(_env("OMNIRAG_MAX_UPLOAD_MB", "50") or 50),
        )

    def with_overrides(self, **kwargs: object) -> Settings:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        if "home" in clean:
            clean["home"] = Path(str(clean["home"])).expanduser()
        return replace(self, **clean)  # type: ignore[arg-type]

    @property
    def ollama_url(self) -> str:
        host = self.ollama_host
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host.rstrip("/")
