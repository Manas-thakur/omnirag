"""Reachability probes for model servers, shared by ``omnirag doctor`` and
``GET /api/status``. Probes never raise: they return a :class:`Probe`."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from omnirag.config import Settings


@dataclass
class Probe:
    name: str
    url: str
    reachable: bool
    detail: str = ""
    latency_ms: float | None = None
    models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(url: str, headers: dict[str, str] | None, timeout: float) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers or {})
    return resp, round((time.perf_counter() - started) * 1000, 1)


def probe_ollama(host: str, timeout: float = 2.0) -> Probe:
    """``GET {host}/api/tags``: reachable if it answers, plus the installed models."""
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    host = host.rstrip("/")
    url = f"{host}/api/tags"
    try:
        resp, ms = _get(url, None, timeout)
        resp.raise_for_status()
        models = [str(m.get("name", "")) for m in resp.json().get("models", []) if m.get("name")]
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        return Probe("ollama", host, False, _short(exc))
    return Probe("ollama", host, True, f"{len(models)} model(s) installed", ms, models)


def probe_openai(base_url: str, api_key: str | None = None, timeout: float = 2.0) -> Probe:
    """``GET {base_url}/models``: reachable if the endpoint answers at all.

    A 401/403 still means the server is up (the key is the problem), which is
    reported in ``detail``.
    """
    base_url = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        resp, ms = _get(f"{base_url}/models", headers, timeout)
    except httpx.HTTPError as exc:
        return Probe("openai", base_url, False, _short(exc))
    if resp.status_code in {401, 403}:
        detail = (
            "reachable, but the API key was rejected" if api_key else "reachable, API key needed"
        )
        return Probe("openai", base_url, True, detail, ms)
    if resp.status_code >= 400:
        return Probe(
            "openai", base_url, True, f"reachable, /models returned HTTP {resp.status_code}", ms
        )
    try:
        models = [str(m.get("id")) for m in resp.json().get("data", []) if m.get("id")]
    except (ValueError, AttributeError):
        models = []
    return Probe("openai", base_url, True, f"{len(models)} model(s) listed", ms, models)


def probe_llm(spec: str, settings: Settings, timeout: float = 2.0) -> Probe | None:
    """Probe the server behind an LLM spec (``none`` -> ``None``)."""
    kind = (spec or "none").partition(":")[0].lower()
    if kind == "ollama":
        return probe_ollama(settings.ollama_url, timeout)
    if kind in {"openai", "openai-compatible"}:
        return probe_openai(settings.openai_base_url, settings.openai_api_key, timeout)
    return None


def _short(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    return text if len(text) <= 160 else text[:157] + "..."
