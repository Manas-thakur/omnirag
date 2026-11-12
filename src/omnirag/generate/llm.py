"""LLM backends over plain HTTP (httpx): Ollama and any OpenAI-compatible API."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from omnirag.config import Settings


class LLMError(RuntimeError):
    """Raised when an LLM backend fails or is misconfigured."""


class LLM(ABC):
    name: str = "llm"

    @abstractmethod
    def complete(
        self, messages: list[dict[str, str]], temperature: float = 0.1, max_tokens: int = 800
    ) -> str: ...


class OllamaLLM(LLM):
    """Ollama chat API (``POST /api/chat``)."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.name = f"ollama:{model}"
        self._client = client or httpx.Client(timeout=timeout)

    def complete(self, messages, temperature=0.1, max_tokens=800) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            resp = self._client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Ollama request to {self.host} failed: {exc}") from exc
        content = (data.get("message") or {}).get("content")
        if content is None:
            raise LLMError("Ollama returned no message content")
        return str(content).strip()


class OpenAICompatibleLLM(LLM):
    """Any ``/chat/completions`` endpoint: OpenAI, vLLM, LM Studio, llama.cpp, Groq, ..."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = f"openai:{model}"
        self._client = client or httpx.Client(timeout=timeout)

    def complete(self, messages, temperature=0.1, max_tokens=800) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data["choices"][0]["message"]["content"] or "").strip()
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"OpenAI-compatible request to {self.base_url} failed: {exc}") from exc


def create_llm(name: str | None, settings: Settings | None = None) -> LLM | None:
    """Build an LLM from a backend name. ``none`` (or empty) returns ``None``,
    which selects the offline extractive answerer.

    Accepted forms: ``none``, ``ollama``, ``ollama:qwen2.5:7b``, ``openai``,
    ``openai:gpt-4o``.
    """
    settings = settings or Settings.from_env()
    name = (name or settings.llm or "none").strip()
    kind, _, model = name.partition(":")
    kind = kind.lower()
    if kind in {"", "none", "extractive", "off"}:
        return None
    if kind == "ollama":
        return OllamaLLM(
            model or settings.ollama_model, settings.ollama_url, settings.request_timeout
        )
    if kind in {"openai", "openai-compatible"}:
        return OpenAICompatibleLLM(
            model or settings.openai_model,
            settings.openai_base_url,
            settings.openai_api_key,
            settings.request_timeout,
        )
    raise LLMError(f"unknown LLM backend {name!r} (use none, ollama or openai)")
