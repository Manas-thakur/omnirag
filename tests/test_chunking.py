from __future__ import annotations

import pytest

from omnirag.chunking import (
    chunk_lines,
    chunk_markdown,
    fixed_size_chunks,
    markdown_sections,
    split_text,
)
from omnirag.textutil import split_sentences, stem, terms, tokenize


def test_split_text_respects_size_and_overlaps():
    text = "\n\n".join(f"Paragraph {i}. " + "lorem ipsum dolor sit amet " * 8 for i in range(20))
    chunks = split_text(text, max_chars=400, overlap=60)
    assert len(chunks) > 5
    assert all(len(c) <= 400 + 60 for c in chunks)
    # Overlap: the start of chunk n+1 repeats words from the end of chunk n.
    tail_words = chunks[0].split()[-3:]
    assert " ".join(tail_words) in chunks[1]


def test_split_text_short_and_empty():
    assert split_text("short text", 100, 10) == ["short text"]
    assert split_text("   ", 100, 10) == []


def test_split_text_handles_unbroken_strings():
    chunks = split_text("x" * 2500, max_chars=1000, overlap=0)
    assert "".join(chunks) == "x" * 2500


def test_fixed_size_chunks():
    text = "".join(chr(ord("a") + i % 26) for i in range(100))
    chunks = fixed_size_chunks(text, size=30, overlap=10)
    assert chunks[0] == text[:30]
    assert chunks[1] == text[20:50]
    assert chunks[0][-10:] == chunks[1][:10]
    assert chunks[-1].endswith(text[-5:])
    with pytest.raises(ValueError):
        fixed_size_chunks("x", size=0)


def test_markdown_sections_ignore_headings_in_code_fences():
    md = "# A\ntext a\n```\n# not a heading\n```\n## B\ntext b\n# C\ntext c"
    sections = markdown_sections(md)
    assert [p for p, _ in sections] == [["A"], ["A", "B"], ["C"]]
    assert "# not a heading" in sections[0][1]


def test_chunk_markdown_prefixes_breadcrumb():
    chunks = chunk_markdown("# Guide\n## Install\nRun pip install.\n", 500, 0)
    assert chunks[0].content == "Guide > Install\n\nRun pip install."
    assert chunks[0].metadata == {"heading": "Guide > Install", "section": "Install"}


def test_chunk_markdown_without_headings():
    chunks = chunk_markdown("just text", 100, 0)
    assert chunks[0].content == "just text"


def test_chunk_lines_windows():
    lines = [f"line {i}" for i in range(1, 26)]
    windows = chunk_lines(lines, max_lines=10, overlap=2)
    assert windows[0][:2] == (1, 10)
    assert windows[1][0] == 9
    assert windows[-1][1] == 25


def test_tokenize_splits_identifiers():
    toks = tokenize("TokenBucket rate_limiter HTTP429")
    assert {"token", "bucket", "tokenbucket", "rate", "limiter"} <= set(toks)


def test_terms_stopwords_and_stemming():
    assert terms("How do the tokens work?") == ["token", "work"]
    assert stem("policies") == "policy"
    assert stem("class") == "class"
    assert stem("status") == "status"


def test_split_sentences():
    text = "First sentence. Second one!\n\n- bullet item\n- another"
    assert split_sentences(text) == ["First sentence.", "Second one!", "- bullet item", "- another"]
