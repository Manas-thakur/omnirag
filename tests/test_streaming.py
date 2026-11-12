"""Streaming answers: LLM stream parsers, AnswerGenerator.stream, KnowledgeBase.ask_stream."""

from __future__ import annotations

import json

import httpx
import pytest

from omnirag.generate import AnswerGenerator, LLMError, OllamaLLM, OpenAICompatibleLLM
from omnirag.generate.llm import LLM
from omnirag.index.knowledge_base import KBPreferences
from omnirag.store.models import Chunk, Modality, ScoredChunk
from omnirag.textutil import TEXT_VERSION


def sc(cid: str, content: str) -> ScoredChunk:
    return ScoredChunk(
        Chunk(cid, "doc-" + cid, content, Modality.TEXT, source=f"/kb/{cid}.md"), 1.0
    )


CHUNKS = [
    sc("a", "Access tokens expire after 15 minutes. Refresh tokens expire after 30 days."),
    sc("b", "Redis caches notes for five minutes."),
]


class PiecesLLM(LLM):
    name = "fake:pieces"

    def __init__(self, pieces, fail_after=None):
        self.pieces = pieces
        self.fail_after = fail_after

    def complete(self, messages, temperature=0.1, max_tokens=800):
        return "".join(self.pieces)

    def stream(self, messages, temperature=0.1, max_tokens=800):
        for i, piece in enumerate(self.pieces):
            if self.fail_after is not None and i >= self.fail_after:
                raise LLMError("connection dropped")
            yield piece


def collect(events):
    sources, deltas, answer = None, [], None
    for event, payload in events:
        if event == "sources":
            sources = payload
        elif event == "delta":
            deltas.append(payload)
        elif event == "answer":
            answer = payload
    return sources, deltas, answer


def test_extractive_stream_matches_generate():
    sources, deltas, answer = collect(AnswerGenerator().stream("when do tokens expire", CHUNKS))
    assert len(sources) == 2
    assert len(deltas) > 3  # emitted progressively, word by word
    assert answer.text == "".join(deltas).strip()
    assert answer.backend == "extractive" and answer.cited
    assert answer.text == AnswerGenerator().generate("when do tokens expire", CHUNKS).text
    assert "first_token_ms" in answer.timings


def test_llm_stream_validates_citations():
    llm = PiecesLLM(["Tokens expire ", "after 15 minutes [1]", " and [9]."])
    _, deltas, answer = collect(AnswerGenerator(llm).stream("q", CHUNKS))
    assert deltas == ["Tokens expire ", "after 15 minutes [1]", " and [9]."]
    assert answer.backend == "fake:pieces"
    assert answer.text == "Tokens expire after 15 minutes [1] and."
    assert answer.cited == [1]


def test_llm_stream_failure_before_first_token_falls_back():
    _, deltas, answer = collect(AnswerGenerator(PiecesLLM(["x"], fail_after=0)).stream("q", CHUNKS))
    assert answer.backend == "extractive" and deltas
    assert any("fell back" in w for w in answer.warnings)


def test_llm_stream_failure_mid_answer_keeps_partial_text():
    llm = PiecesLLM(["Partial answer [1]", " never sent"], fail_after=1)
    _, _, answer = collect(AnswerGenerator(llm).stream("q", CHUNKS))
    assert answer.text == "Partial answer [1]"
    assert answer.backend == "fake:pieces"
    assert any("incomplete" in w for w in answer.warnings)


def test_llm_stream_failure_without_fallback_raises():
    gen = AnswerGenerator(PiecesLLM(["x"], fail_after=0), fallback=False)
    with pytest.raises(LLMError):
        collect(gen.stream("q", CHUNKS))


def test_base_llm_stream_yields_complete():
    class Whole(LLM):
        def complete(self, messages, temperature=0.1, max_tokens=800):
            return "all at once"

    assert list(Whole().stream([])) == ["all at once"]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_stream_parses_ndjson():
    lines = [
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " world [1]"}, "done": False},
        {"message": {"content": ""}, "done": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True and request.url.path == "/api/chat"
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines) + "\n")

    llm = OllamaLLM("m", "http://ollama", client=_client(handler))
    assert list(llm.stream([{"role": "user", "content": "hi"}])) == ["Hello", " world [1]"]


def test_ollama_stream_errors_become_llm_errors():
    llm = OllamaLLM(
        "m",
        "http://ollama",
        client=_client(lambda r: httpx.Response(200, text='{"error":"no model"}\n')),
    )
    with pytest.raises(LLMError, match="no model"):
        list(llm.stream([]))
    down = OllamaLLM("m", "http://ollama", client=_client(lambda r: httpx.Response(500)))
    with pytest.raises(LLMError):
        list(down.stream([]))


def test_openai_stream_parses_sse():
    events = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Tokens"}}]},
        {"choices": []},
        {"choices": [{"delta": {"content": " rotate [2]"}}]},
    ]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text=": keep-alive\n\n" + body)

    llm = OpenAICompatibleLLM("gpt", "http://api/v1", "sk-test", client=_client(handler))
    assert list(llm.stream([])) == ["Tokens", " rotate [2]"]


def test_openai_stream_http_error():
    llm = OpenAICompatibleLLM("gpt", "http://api/v1", client=_client(lambda r: httpx.Response(401)))
    with pytest.raises(LLMError):
        list(llm.stream([]))


def test_kb_ask_stream(demo_kb):
    events = list(demo_kb.ask_stream("How are refresh tokens rotated?", llm="none", k=3))
    kinds = [e for e, _ in events]
    assert kinds[0] == "sources" and kinds[-1] == "answer" and "delta" in kinds
    sources = events[0][1]
    assert len(sources["sources"]) == 3 and sources["query"]["intent"]
    answer = events[-1][1]
    assert answer.cited and answer.timings["total_ms"] >= answer.timings["retrieve_ms"]
    assert answer.query["mode"] == "hybrid"


def test_kb_preferences_roundtrip_and_llm(demo_kb):
    assert demo_kb.preferences == KBPreferences()
    assert demo_kb.default_llm() is None  # server default "none"
    demo_kb.save_preferences(
        KBPreferences(llm="openai", model="m1", base_url="http://x/v1/", top_k=7)
    )
    prefs = demo_kb.preferences
    assert prefs.base_url == "http://x/v1" and prefs.top_k == 7
    llm = demo_kb.default_llm()
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.model == "m1" and llm.base_url == "http://x/v1"
    demo_kb.save_preferences(KBPreferences(llm="ollama", base_url="http://gpu:11434"))
    llm = demo_kb.default_llm()
    assert isinstance(llm, OllamaLLM) and llm.host == "http://gpu:11434"
    demo_kb.save_preferences(KBPreferences(llm="none", model="ignored"))
    assert demo_kb.default_llm() is None
    for bad in (
        {"llm": "magic"},
        {"base_url": "ftp://x"},
        {"top_k": 0},
        {"top_k": 51},
        {"top_k": True},
    ):
        with pytest.raises(ValueError):
            KBPreferences.from_dict(bad)
    # A corrupt settings file falls back to defaults instead of breaking queries.
    demo_kb.preferences_path.write_text("{not json", encoding="utf-8")
    assert demo_kb.preferences == KBPreferences()


def test_old_kbs_are_reembedded_after_stemmer_upgrade(manager, corpus):
    kb = manager.create("legacy")
    kb.ingest([corpus / "docs"])
    assert kb.config.text_version == TEXT_VERSION
    kb.config.text_version = 1
    kb.config.save(kb.path / "kb.json")
    kb.close()

    reopened = manager.get("legacy")
    assert reopened.config.text_version == 1
    hits = reopened.search("when do refresh tokens expire", k=2)
    assert hits.results
    assert reopened.config.text_version == TEXT_VERSION
    assert reopened.ensure_current() is False
    reopened.close()
    with manager.get("legacy") as again:
        assert again.config.text_version == TEXT_VERSION
