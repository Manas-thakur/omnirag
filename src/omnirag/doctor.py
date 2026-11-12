"""Environment checks behind ``omnirag doctor``."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from omnirag import __version__
from omnirag.config import Settings
from omnirag.health import probe_ollama, probe_openai

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

#: extra name -> (importable modules, what it enables)
EXTRAS: dict[str, tuple[tuple[str, ...], str]] = {
    "server": (("fastapi", "uvicorn", "multipart"), "web UI and HTTP API"),
    "pdf": (("pypdf",), "PDF text extraction"),
    "images": (("PIL",), "image metadata (EXIF, dimensions)"),
    "audio": (("faster_whisper",), "local audio transcription"),
    "embeddings": (("sentence_transformers",), "neural sentence-transformers embedders"),
}


@dataclass
class Check:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def run_checks(
    settings: Settings, home: Path | None = None, network: bool = True, timeout: float = 2.0
) -> list[Check]:
    checks: list[Check] = []
    add = lambda name, status, detail: checks.append(Check(name, status, detail))  # noqa: E731

    # Python and package
    py_ok = sys.version_info >= (3, 10)
    add(
        "python",
        OK if py_ok else FAIL,
        f"{platform.python_version()} ({sys.executable})"
        + ("" if py_ok else " - OmniRAG needs Python 3.10+"),
    )
    add("omnirag", INFO, f"version {__version__}")

    # Data directory (checked without creating anything)
    home = Path(home or settings.home).expanduser()
    if home.is_dir():
        kb_root = home / "kbs"
        kbs = (
            sorted(p.name for p in kb_root.iterdir() if (p / "kb.json").is_file())
            if kb_root.is_dir()
            else []
        )
        listing = ", ".join(kbs[:6]) + (" ..." if len(kbs) > 6 else "")
        if os.access(home, os.W_OK):
            add(
                "data dir",
                OK,
                f"{home} is writable; {len(kbs)} knowledge base(s)"
                + (f": {listing}" if kbs else ""),
            )
        else:
            add("data dir", FAIL, f"{home} is not writable")
    elif home.exists():
        add("data dir", FAIL, f"{home} exists but is not a directory")
    else:
        parent = next((p for p in home.parents if p.exists()), None)
        if parent is not None and os.access(parent, os.W_OK):
            add("data dir", OK, f"{home} does not exist yet; it will be created on first use")
        else:
            add("data dir", FAIL, f"{home} does not exist and cannot be created")

    # Embedder
    spec = settings.embedder
    kind = spec.partition(":")[0]
    if kind == "hashing":
        add("embedder", OK, f"{spec} (built in, offline, no downloads)")
    elif kind == "st":
        if _installed("sentence_transformers"):
            add("embedder", OK, f"{spec} (sentence-transformers installed)")
        else:
            add(
                "embedder",
                FAIL,
                f"{spec} needs sentence-transformers: pip install 'omnirag[embeddings]'",
            )
    elif kind == "ollama":
        add("embedder", INFO, f"{spec} (served by Ollama at {settings.ollama_url})")
    else:
        add("embedder", FAIL, f"unknown embedder spec {spec!r}")

    # LLM backends
    llm_kind = settings.llm.partition(":")[0].lower()
    add("default llm", INFO, settings.llm + ("" if llm_kind != "none" else " (extractive answers)"))
    needs_ollama = llm_kind == "ollama" or kind == "ollama" or bool(settings.vlm_model)
    needs_openai = llm_kind in {"openai", "openai-compatible"}
    if not network:
        add("ollama", INFO, "skipped (--no-network)")
        add("openai", INFO, "skipped (--no-network)")
    else:
        p = probe_ollama(settings.ollama_url, timeout)
        if p.reachable:
            model = settings.llm.partition(":")[2] or settings.ollama_model
            detail = f"{p.url} reachable ({p.latency_ms:.0f} ms), {len(p.models)} model(s)"
            status = OK
            if llm_kind == "ollama" and p.models and not _has_model(p.models, model):
                status, detail = WARN, detail + f"; model {model!r} is not pulled"
            add("ollama", status, detail)
        else:
            add(
                "ollama",
                FAIL if needs_ollama else WARN,
                f"{p.url} not reachable ({p.detail})"
                + ("" if needs_ollama else " - optional, only needed for --llm ollama"),
            )
        configured = (
            needs_openai
            or bool(settings.openai_api_key)
            or settings.openai_base_url != "https://api.openai.com/v1"
        )
        if configured:
            o = probe_openai(settings.openai_base_url, settings.openai_api_key, timeout)
            status = OK if o.reachable and "rejected" not in o.detail else WARN
            if not o.reachable:
                status = FAIL if needs_openai else WARN
            add(
                "openai",
                status,
                f"{o.url}: {o.detail}" if o.reachable else f"{o.url} not reachable ({o.detail})",
            )
        else:
            add("openai", INFO, "not configured (set OPENAI_BASE_URL / OPENAI_API_KEY)")

    # Optional extras
    for extra, (modules, purpose) in EXTRAS.items():
        missing = [m for m in modules if not _installed(m)]
        if missing:
            add(
                f"extra: {extra}",
                WARN if extra == "server" else INFO,
                f"not installed - {purpose} (pip install 'omnirag[{extra}]')",
            )
        else:
            add(f"extra: {extra}", OK, f"installed - {purpose}")

    # Server hardening hints
    add(
        "api key",
        INFO,
        "OMNIRAG_API_KEY is set (API requires a key)"
        if settings.api_key
        else "OMNIRAG_API_KEY not set (fine for localhost; set it before exposing the server)",
    )
    return checks


def _has_model(models: list[str], wanted: str) -> bool:
    base = wanted if ":" in wanted else f"{wanted}:latest"
    return any(m in (wanted, base) for m in models)
