from __future__ import annotations

from omnirag.query import (
    ModalityRouter,
    QueryIntent,
    QueryParser,
    QueryRewriter,
    detect_intent,
    detect_modality_hints,
)
from omnirag.store.models import Modality, SearchFilters


def test_parse_inline_filters():
    p = QueryParser().parse(
        'modality:code,table -type:image source:*.py lang:Python "token bucket" refill rate'
    )
    assert p.filters.modalities == [Modality.CODE, Modality.TABLE]
    assert p.filters.exclude_modalities == [Modality.IMAGE]
    assert p.filters.sources == ["*.py"]
    assert p.filters.metadata == {"language": "python"}
    assert p.phrases == ["token bucket"]
    assert p.text == "token bucket refill rate"


def test_parse_keeps_unknown_filters_and_urls_as_text():
    p = QueryParser().parse("what is modality:hologram at https://example.com speaker:Priya")
    assert "modality:hologram" in p.text
    assert "https://example.com" in p.text
    assert p.filters.metadata == {"speaker": "Priya"}
    assert p.filters.modalities is None


def test_parse_handles_apostrophes():
    p = QueryParser().parse("what's the team's decision?")
    assert p.text == "what's the team's decision?"


def test_intent_detection():
    assert detect_intent("Compare GPTQ vs AWQ") == QueryIntent.COMPARATIVE
    assert detect_intent("Show me the implementation of the limiter") == QueryIntent.CODE
    assert detect_intent("How do I configure the cache?") == QueryIntent.PROCEDURAL
    assert detect_intent("Why is latency high?") == QueryIntent.EXPLANATORY
    assert detect_intent("Summarize the meeting") == QueryIntent.SUMMARIZATION
    assert detect_intent("What is the default rate?") == QueryIntent.FACTUAL
    assert detect_intent("rate limits") == QueryIntent.EXPLORATORY


def test_modality_hints():
    hints = detect_modality_hints("Show the architecture diagram and the function that does it")
    assert Modality.IMAGE in hints and Modality.CODE in hints
    assert detect_modality_hints("what was decided in the meeting") == [Modality.AUDIO]
    assert detect_modality_hints("hello") == []


def test_router_soft_boosts_and_hard_filters():
    router = ModalityRouter()
    parsed = QueryParser().parse("show me the diagram")
    plan = router.route(parsed, k=4)
    assert plan.boost_for(Modality.IMAGE) > 1.0
    assert plan.boost_for(Modality.TEXT) == 1.0
    assert plan.filters.is_empty()
    assert plan.candidate_k >= 20

    hard = router.route(
        QueryParser().parse("modality:code diagram"),
        extra_filters=SearchFilters(sources=["src/"]),
    )
    assert hard.filters.modalities == [Modality.CODE]
    assert hard.filters.sources == ["src/"]
    assert hard.boosts == {}


def test_rewriter_expansion_and_sparse_query():
    rw = QueryRewriter()
    parsed = QueryParser().parse("how does auth work with the db?")
    expanded = rw.expand(parsed.text)
    assert "authentication" in expanded and "database" in expanded
    sparse = rw.sparse_query(parsed)
    assert sparse.startswith("auth work db")
    assert rw.hyde("anything") is None


def test_rewriter_hyde_with_llm():
    class FakeLLM:
        name = "fake"

        def complete(self, messages, temperature=0.1, max_tokens=800):
            return "  A hypothetical passage.  "

    assert QueryRewriter(FakeLLM()).hyde("q") == "A hypothetical passage."
