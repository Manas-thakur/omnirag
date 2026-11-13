"""Runtime configuration, resolved from environment variables.

Every setting has a sensible offline default so OmniRAG works out of the box
without any model server. Remote backends (Ollama, OpenAI-compatible APIs) are
only contacted when explicitly selected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO_URL = "https://github.com/Manas-thakur/omnirag"


class ConfigError(ValueError):
    """An invalid setting (environment variable or argument)."""


def install_hint(extra: str | None = None) -> str:
    """The command that installs OmniRAG (with an optional extra) from GitHub.

    OmniRAG is not published on PyPI, so ``pip install omnirag[...]`` would not
    work; the GitHub form does.
    """
    name = f"omnirag[{extra}]" if extra else "omnirag"
    return f'pip install "{name} @ git+{REPO_URL}"'


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_number(name: str, default: str, kind: type, minimum: float | None = None):
    raw = _env(name, default) or default
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be at least {minimum:g}, got {raw!r}")
    return value


def validate_chunking(chunk_size: int, chunk_overlap: int) -> None:
    """Chunks must have a positive size and an overlap smaller than the size."""
    if chunk_size < 50:
        raise ConfigError(f"chunk size must be at least 50 characters, got {chunk_size}")
    if chunk_overlap < 0:
        raise ConfigError(f"chunk overlap must not be negative, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ConfigError(
            f"chunk overlap ({chunk_overlap}) must be smaller than the chunk size ({chunk_size})"
        )


def _ingest_roots() -> tuple[Path, ...]:
    raw = _env("OMNIRAG_INGEST_ROOTS", "") or ""
    return tuple(Path(p.strip()).expanduser() for p in raw.split(os.pathsep) if p.strip())


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
    #: Directories ``POST /api/ingest`` may read from (empty: the server's
    #: working directory). Uploads and the CLI are not restricted.
    ingest_roots: tuple[Path, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        """Settings from ``OMNIRAG_*`` (and Ollama/OpenAI) environment variables.

        Raises :class:`ConfigError` for values that are not valid.
        """
        settings = cls._from_env()
        validate_chunking(settings.chunk_size, settings.chunk_overlap)
        return settings

    @classmethod
    def _from_env(cls) -> Settings:
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
            request_timeout=_env_number("OMNIRAG_TIMEOUT", "120", float, minimum=0.001),
            chunk_size=_env_number("OMNIRAG_CHUNK_SIZE", "1200", int),
            chunk_overlap=_env_number("OMNIRAG_CHUNK_OVERLAP", "150", int),
            api_key=_env("OMNIRAG_API_KEY"),
            cors_origins=tuple(
                o.strip().rstrip("/")
                for o in (_env("OMNIRAG_CORS_ORIGINS", "") or "").split(",")
                if o.strip()
            ),
            max_upload_mb=_env_number("OMNIRAG_MAX_UPLOAD_MB", "50", float, minimum=0.001),
            ingest_roots=_ingest_roots(),
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
