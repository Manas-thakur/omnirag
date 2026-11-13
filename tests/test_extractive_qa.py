"""Offline answer quality regressions from the v0.3.0 QA pass."""

from __future__ import annotations

from pathlib import Path

from omnirag.generate import AnswerGenerator
from omnirag.generate.citation import Source
from omnirag.generate.extractive import ExtractiveAnswerer, TermWeights
from omnirag.store.models import Chunk, Modality, ScoredChunk
from omnirag.textutil import split_sentences


def src(index: int, content: str, modality: str = "text", **meta) -> Source:
    return Source(
        index=index,
        chunk_id=f"c{index}",
        doc_id=f"d{index}",
        source=f"/kb/{meta.get('path', f'doc{index}.md')}",
        title=meta.pop("title", ""),
        modality=modality,
        score=1.0,
        content=content,
        snippet=content[:80],
        metadata=meta,
    )


def _filler(docs: Path, n: int = 24) -> None:
    for i in range(n):  # enough chunks for document frequencies to mean something
        (docs / f"page{i}.md").write_text(
            f"# Page {i}\n\nThis page covers topic number {i} of the product in detail.\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------- (a) floor
def test_off_topic_question_gets_the_honest_not_found(manager, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "detectors.md").write_text(
        "# Detectors\n\nHalf of the anomalies are point anomalies far from the rest.\n\n"
        "## CUSUM\n\nUse only the first N points as the reference level. "
        "Catches level shifts and drift.\n",
        encoding="utf-8",
    )
    _filler(docs)
    kb = manager.create("anomalies")
    kb.ingest([docs])
    answer = kb.ask("What is the boiling point of water at sea level?")
    assert "couldn't find" in answer.text
    assert answer.cited == []
    # A real question about the same chunk is still answered.
    ok = kb.ask("Which detector catches level shifts?")
    assert "Catches level shifts and drift." in ok.text and ok.cited
    kb.close()


def test_weights_make_rare_question_words_count():
    weights = TermWeights({"point": 3.0, "level": 3.0}, documents=500)
    assert weights("boil") > weights("point")  # never seen: weighs the most
    assert weights("everywhere") == weights.unseen
    assert TermWeights({"product": 0.01}, 10)("product") == 1.0  # floor


# -------------------------------------------------------- (b) short answers
def test_short_sentence_that_answers_is_kept():
    text = ExtractiveAnswerer().answer(
        "When is lunch?", [src(1, "Agenda\n\nLunch is at one pm.\n\nTalks resume after.")]
    )
    assert "Lunch is at one pm. [1]" in text


# ----------------------------------------------------- (c) headings and alts
def test_section_heading_beats_a_passing_mention():
    auth = src(
        1,
        "Guide > Authentication\n\nAuthentication uses short-lived tokens.",
        heading="Guide > Authentication",
    )
    cache = src(
        2,
        "Guide > Caching\n\nThe cache is cleared after authentication.",
        heading="Guide > Caching",
    )
    text = ExtractiveAnswerer(max_sentences=1).answer(
        "How does authentication work?", [cache, auth]
    )
    assert "short-lived tokens" in text


def test_image_alt_text_does_not_answer_when_prose_does():
    content = (
        "Incidents > Triage\n\n(Image: Incident cards with triage buttons)\n\n"
        "Each incident card has Mark as normal, Confirm and Mute buttons."
    )
    image = src(2, "Image: triage (triage.png)\nCaption: Incident triage buttons", "image")
    text = ExtractiveAnswerer().answer(
        "Which buttons does an incident have?",
        [src(1, content, heading="Incidents > Triage"), image],
    )
    assert "Mark as normal, Confirm and Mute buttons" in text
    assert "Incident cards with triage buttons" not in text
    assert "[2]" not in text


# --------------------------------------------------------- (d) markdown noise
def test_markdown_noise_is_never_quoted():
    content = (
        "Install > Usage\n\n"
        # A chunk that starts inside a badge link and in the middle of a sentence.
        "MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)\n"
        "the previous chunk ended in the middle of this sentence about installing.\n\n"
        "![Python](https://img.shields.io/badge/python-3.12-blue) Installing takes a minute.\n\n"
        "```bash\ninstall --model mock   # installing the demo\n```\n\n"
        "```\n+--------+     +---------+\n| client | --> | install |\n+--------+     +---------+\n```\n\n"
        "┌──────────┐\n│ installer │\n└──────────┘\n\n"
        "Installing needs a local model, e.g. Ollama or LM Studio, i.e. Nothing in the cloud.\n\n"
        "MIT © 2026 Example Installers\n"
    )
    text = ExtractiveAnswerer().answer(
        "What does installing need?", [src(1, content, heading="Install > Usage")]
    )
    assert "e.g. Ollama or LM Studio, i.e. Nothing in the cloud." in text
    for noise in ("the previous chunk", "shields.io", "](", "--model", "+----", "│", "©", "MIT"):
        assert noise not in text, noise


def test_sentence_splitter_keeps_abbreviations_together():
    assert split_sentences("Use a model, e.g. Ollama. Or vs. IVF. Done.") == [
        "Use a model, e.g. Ollama.",
        "Or vs. IVF.",
        "Done.",
    ]


def test_code_block_cut_at_a_chunk_boundary_is_dropped():
    content = "Usage\n\n    --flag value\n    other --option\n```\n\nThe flag sets the value."
    text = ExtractiveAnswerer().answer(
        "What does the flag set?", [src(1, content, heading="Usage")]
    )
    assert "--option" not in text and "The flag sets the value. [1]" in text


# ------------------------------------------------------ (e) code and citations
CODE = ScoredChunk(
    Chunk(
        "code",
        "doc-code",
        "Python function `allow` in src/x.py (lines 1-5)\nSignature: def allow(self)\n"
        "Documentation: Consume a token if one is available.\n"
        "```python\ndef allow(self):\n    return True\n```",
        Modality.CODE,
        source="/kb/x.py",
        metadata={"symbol": "allow", "kind": "function", "language": "python"},
    ),
    1.0,
)
PROSE = ScoredChunk(
    Chunk(
        "prose",
        "doc-prose",
        "Each request consumes a token from the bucket.",
        Modality.TEXT,
        source="/kb/limits.md",
    ),
    0.9,
)


def test_code_block_only_for_code_questions():
    plain = AnswerGenerator().generate("When is a token consumed?", [CODE, PROSE])
    assert "```" not in plain.text
    about_code = AnswerGenerator().generate(
        "Show the function that consumes a token", [CODE, PROSE]
    )
    assert "```python" in about_code.text
    by_name = AnswerGenerator().generate("how does allow() consume a token", [CODE, PROSE])
    assert "```python" in by_name.text


def test_bracketed_numbers_in_quotes_are_not_citations():
    chunks = [
        ScoredChunk(
            Chunk(
                "a",
                "doc-a",
                "Read the third item with items[2] in the list.",
                Modality.TEXT,
                source="/kb/a.md",
            ),
            1.0,
        ),
        ScoredChunk(
            Chunk("b", "doc-b", "Unrelated text about zebras.", Modality.TEXT, source="/kb/b.md"),
            0.5,
        ),
    ]
    answer = AnswerGenerator().generate("How do I read the third item?", chunks)
    assert answer.cited == [1]
    assert "items[" in answer.text


# ---------------------------------------------------------- (f) changelogs
def test_what_changed_in_a_version_reads_the_changelog(manager, tmp_path):
    docs = tmp_path / "acme"
    docs.mkdir()
    (docs / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.3.0] - 2026-11-01\n\n### Added\n\n"
        "- A review inbox for flagged values.\n- Dark mode for the web app.\n\n"
        "## [0.2.0] - 2026-06-01\n\n### Added\n\n- CSV export of findings.\n",
        encoding="utf-8",
    )
    (docs / "README.md").write_text(
        "# Acme\n\nAcme 0.3.0 is the current version. Acme finds anomalies in tables.\n",
        encoding="utf-8",
    )
    _filler(docs)
    kb = manager.create("acme")
    kb.ingest([docs])
    answer = kb.ask("What changed in Acme 0.3.0?")
    assert "A review inbox for flagged values." in answer.text
    assert "Dark mode for the web app." in answer.text
    assert "CSV export" not in answer.text
    cited = [s for s in answer.sources if s.index in answer.cited]
    assert all("CHANGELOG" in s.source for s in cited)
    kb.close()


# ------------------------------------------------------- (g) partial lists
def test_table_listing_says_when_it_is_partial(manager, tmp_path):
    docs = tmp_path / "shop"
    docs.mkdir()
    rows = ["order_id,status,amount"]
    for i in range(1, 61):
        rows.append(f"A{i},{'returned' if i % 5 == 0 else 'delivered'},{i * 10}.50")
    (docs / "orders.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    kb = manager.create("shop")
    kb.ingest([docs])
    answer = kb.ask("Which orders have status returned?")
    assert "status=returned" in answer.text
    assert "matching rows in orders.csv" in answer.text
    assert "of 12 matching rows" in answer.text
    kb.close()


def test_unfenced_ascii_diagram_with_pipes_is_not_a_table():
    content = (
        "Architecture\n\n+--------+     +---------+\n| client | --> | gateway |\n"
        "+--------+     +---------+\n\nThe gateway checks every client request.\n\n"
        "| Option | Default |\n|---|---|\n| `--port` | `8000` |\n"
    )
    text = ExtractiveAnswerer().answer(
        "What does the gateway check, and what is the default port?",
        [src(1, content, heading="Architecture")],
    )
    assert "-->" not in text and "client:" not in text
    assert "The gateway checks every client request." in text
    assert "--port: default 8000" in text
