from __future__ import annotations

import json

import httpx
import pytest

from omnirag.config import Settings
from omnirag.generate import (
    AnswerGenerator,
    CitationTracker,
    ContextAssembler,
    ExtractiveAnswerer,
    LLMError,
    OllamaLLM,
    OpenAICompatibleLLM,
    build_messages,
    create_llm,
)
from omnirag.generate.llm import LLM
from omnirag.store.models import Chunk, Modality, ScoredChunk


def sc(cid: str, content: str, modality=Modality.TEXT, **meta) -> ScoredChunk:
    return ScoredChunk(
        Chunk(cid, "doc-" + cid, content, modality, source=f"/kb/{cid}.md", metadata=meta), 1.0
    )


CHUNKS = [
    sc(
        "auth",
        "Access tokens expire after 15 minutes. Refresh tokens expire after 30 days.",
        heading="Auth",
    ),
    sc("cache", "Redis caches notes for five minutes. Writes invalidate the cache."),
    sc(
        "code",
        "Python function `allow` in src/x.py (lines 1-5)\nSignature: def allow(self)\n"
        "Documentation: Consume a token if one is available.\n```python\ndef allow(self):\n    return True\n```",
        Modality.CODE,
        symbol="allow",
        kind="function",
        language="python",
        line_start=1,
        line_end=5,
    ),
]


def test_citation_tracker_validate_and_bibliography():
    _, tracker = ContextAssembler().assemble(CHUNKS)
    text, cited = tracker.validate("Tokens expire [1]. Cache [2, 9]. Bogus [7].")
    assert text == "Tokens expire [1]. Cache [2]. Bogus."
    assert cited == [1, 2]
    assert CitationTracker.extract("a [3] b [1,2] c [3]") == [3, 1, 2]
    bib = tracker.bibliography(only=[1])
    assert bib.startswith("[1]") and "[2]" not in bib
    src = tracker.sources[3]
    assert src.location == "lines 1-5"
    assert src.to_dict()["label"] == "code.md lines 1-5"


def test_context_assembler_respects_budget():
    big = [sc(str(i), "word " * 400) for i in range(10)]
    context, tracker = ContextAssembler(max_tokens=1200).assemble(big)
    assert 1 <= len(tracker.sources) < 10
    assert "[1] (text) /kb/0.md" in context


def test_context_assembler_includes_neighbors_when_room():
    hit = sc("mid", "middle part")
    hit.context_before = [Chunk("b", "doc-mid", "before part", Modality.TEXT)]
    context, tracker = ContextAssembler().assemble([hit])
    assert "before part\n...\nmiddle part" in context
    assert tracker.sources[1].context_before == "before part"


def test_build_messages():
    msgs = build_messages("Q?", "[1] ctx")
    assert msgs[0]["role"] == "system" and "[n]" not in msgs[0]["content"][:5]
    assert "Question: Q?" in msgs[1]["content"]


def test_extractive_answer_cites_relevant_sentences():
    _, tracker = ContextAssembler().assemble(CHUNKS)
    text = ExtractiveAnswerer().answer(
        "When do access tokens expire?", list(tracker.sources.values())
    )
    assert "Access tokens expire after 15 minutes. [1]" in text
    assert "Redis" not in text


def test_extractive_answer_includes_code():
    _, tracker = ContextAssembler().assemble(CHUNKS)
    text = ExtractiveAnswerer().answer(
        "how does allow consume a token", list(tracker.sources.values())
    )
    assert "`allow` (function): Consume a token" in text
    assert "```python" in text


def test_extractive_answer_without_sources_or_matches():
    assert "could not find" in ExtractiveAnswerer().answer("x", [])
    _, tracker = ContextAssembler().assemble(CHUNKS[:1])
    text = ExtractiveAnswerer().answer("zebra giraffe", list(tracker.sources.values()))
    assert "couldn't find" in text and "closest match" in text and "[1]" in text
    # The unrelated chunk's content must not be presented as an answer.
    assert CHUNKS[0].chunk.content[:40] not in text


def test_extractive_summary_uses_named_document_in_order():
    from omnirag.generate.extractive import is_summary_question

    assert is_summary_question("Summarise the auth docs")
    assert is_summary_question("What does latency.csv contain?")
    assert not is_summary_question("When do access tokens expire?")
    _, tracker = ContextAssembler().assemble(CHUNKS)
    sources = list(tracker.sources.values())
    focus = sources[0]
    name = str(focus.metadata.get("path") or focus.label)
    text = ExtractiveAnswerer().answer(f"Summarise {name}", sources)
    lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    assert len(lines) >= 2
    assert all(f"[{focus.index}]" in ln for ln in lines)


class FakeLLM(LLM):
    name = "fake:model"

    def __init__(self, reply: str = "Tokens expire after 15 minutes [1] [5].", fail: bool = False):
        self.reply, self.fail, self.calls = reply, fail, []

    def complete(self, messages, temperature=0.1, max_tokens=800):
        self.calls.append(messages)
        if self.fail:
            raise LLMError("boom")
        return self.reply


def test_generator_with_llm_validates_citations():
    llm = FakeLLM()
    answer = AnswerGenerator(llm).generate("When do tokens expire?", CHUNKS)
    assert answer.backend == "fake:model"
    assert answer.text == "Tokens expire after 15 minutes [1]."
    assert answer.cited == [1]
    assert [s.index for s in answer.cited_sources] == [1]
    assert "Sources:" in llm.calls[0][1]["content"]
    data = answer.to_dict()
    assert data["answer"] == answer.text and len(data["sources"]) == 3


def test_generator_falls_back_when_llm_fails():
    answer = AnswerGenerator(FakeLLM(fail=True)).generate("When do access tokens expire?", CHUNKS)
    assert answer.backend == "extractive"
    assert answer.warnings and "fell back" in answer.warnings[0]
    assert answer.cited
    with pytest.raises(LLMError):
        AnswerGenerator(FakeLLM(fail=True), fallback=False).generate("q", CHUNKS)


def test_generator_warns_on_uncited_llm_answer():
    answer = AnswerGenerator(FakeLLM("No citations here.")).generate("q", CHUNKS)
    assert any("no valid" in w for w in answer.warnings)


def test_ollama_llm_payload_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": " hi [1] "}})

    llm = OllamaLLM(
        "llama3.1:8b",
        "http://ollama.test:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert llm.complete([{"role": "user", "content": "q"}], max_tokens=50) == "hi [1]"
    assert seen["url"] == "http://ollama.test:11434/api/chat"
    assert seen["body"]["stream"] is False and seen["body"]["options"]["num_predict"] == 50


def test_openai_compatible_llm():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "gpt-test"
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer [1]"}}]})

    llm = OpenAICompatibleLLM(
        "gpt-test",
        "http://llm.test/v1",
        "sk-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert llm.complete([{"role": "user", "content": "q"}]) == "answer [1]"


def test_llm_errors_are_wrapped():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(LLMError):
        OllamaLLM("m", "http://x.test", client=client).complete([])
    bad = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []}))
    )
    with pytest.raises(LLMError):
        OpenAICompatibleLLM("m", "http://x.test/v1", client=bad).complete([])


def test_create_llm():
    s = Settings(ollama_host="http://h:1", ollama_model="qwen", openai_model="gpt-x")
    assert create_llm("none", s) is None
    assert create_llm("", s) is None
    o = create_llm("ollama", s)
    assert isinstance(o, OllamaLLM) and o.model == "qwen" and o.host == "http://h:1"
    assert create_llm("ollama:llama3.2:3b", s).model == "llama3.2:3b"
    assert create_llm("openai", s).model == "gpt-x"
    with pytest.raises(LLMError):
        create_llm("mystery", s)
