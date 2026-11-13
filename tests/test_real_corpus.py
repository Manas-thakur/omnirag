"""Regressions found by using OmniRAG on a real docs corpus (Starlight/MDX docs
plus READMEs that repeat the product name everywhere)."""

from __future__ import annotations

from pathlib import Path

from omnirag.generate.citation import Source
from omnirag.generate.extractive import ExtractiveAnswerer, _is_nav_line
from omnirag.ingest.base import IngestContext
from omnirag.ingest.text import TextIngestor
from omnirag.retrieve.context import context_header, index_text
from omnirag.retrieve.rerank import query_phrases

MDX = """---
title: Incidents
description: How findings are grouped and triaged.
---

import Shot from '../../components/Shot.astro';

People act on **incidents** instead of single findings.

<Shot name="incidents.png" alt="Incident cards with the expected range shaded" />

## Triage

| Action | What it does |
|---|---|
| **Mark as normal** | Records every finding as a false positive. |
| **Mute 24h** | Hides this kind of incident on this column for 24 hours. |
"""


def _ingest(tmp_path: Path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return TextIngestor().ingest(path, IngestContext(root=tmp_path))


def test_mdx_front_matter_title_becomes_breadcrumb_and_jsx_is_dropped(tmp_path):
    doc = _ingest(tmp_path, "incidents.mdx", MDX)
    assert doc.title == "Incidents"
    text = "\n".join(c.content for c in doc.chunks)
    assert "import Shot" not in text and "<Shot" not in text
    assert "Incident cards with the expected range shaded" in text  # alt text kept
    triage = next(c for c in doc.chunks if c.metadata.get("section") == "Triage")
    assert triage.metadata["heading"] == "Incidents > Triage"


def test_index_text_adds_path_and_title_context():
    meta = {"path": "anomalyguard-docs/concepts/incidents.mdx", "title": "Incidents"}
    assert context_header(meta) == "anomalyguard docs concepts incidents"
    assert index_text("Triage\n\nbody", meta).startswith("anomalyguard docs concepts incidents\n")
    other = {"path": "notes/a.md", "title": "Release plan"}
    assert context_header(other) == "notes a | Release plan"
    assert index_text("x", {}) == "x"


def test_extractive_answer_reads_table_rows_and_skips_nav_lines():
    assert _is_nav_line("**[Website](https://x)** · **[Docs](https://y)** ·")
    assert _is_nav_line("[![CI](https://b.svg)](https://ci)")
    assert not _is_nav_line("See [the docs](https://x) for more.")
    content = (
        "Incidents > Triage\n\n**[Docs](https://x)** · **[Releases](https://y)**\n\n"
        "| Action | What it does |\n|---|---|\n"
        "| **Mute 24h** | Hides this kind of incident on this column for 24 hours. |"
    )
    src = Source(
        index=1,
        chunk_id="c1",
        doc_id="d1",
        source="incidents.mdx",
        title="Incidents",
        modality="text",
        score=1.0,
        content=content,
        snippet=content[:80],
        metadata={"heading": "Incidents > Triage", "path": "incidents.mdx"},
    )
    text = ExtractiveAnswerer().answer("How do I mute an incident and for how long?", [src])
    assert "Mute 24h: Hides this kind of incident on this column for 24 hours." in text
    assert "Releases" not in text


def test_query_phrases_keep_multiword_names_not_scaffolding():
    phrases = query_phrases("What does Mark as normal do?")
    assert " mark as normal " in phrases
    assert not any(p.strip().startswith(("what", "does")) for p in phrases)


def test_product_name_does_not_drown_the_answer(manager, tmp_path):
    """A word in most chunks (the product name) must not outrank the page that answers."""
    docs = tmp_path / "corpus"
    (docs / "acme-docs").mkdir(parents=True)
    (docs / "acme-README.md").write_text(
        "# Acme\n\nAcme is a tool. Acme runs anywhere. Acme is fast. Acme Acme.\n\n"
        "## License\n\nAcme is MIT licensed.\n",
        encoding="utf-8",
    )
    (docs / "acme-docs" / "incidents.mdx").write_text(MDX, encoding="utf-8")
    for i in range(24):  # enough chunks for document frequencies to mean something
        (docs / "acme-docs" / f"page{i}.md").write_text(
            f"---\ntitle: Page {i}\n---\n\nAcme page {i} covers topic number {i} in detail.\n",
            encoding="utf-8",
        )
    kb = manager.create("acme")
    kb.ingest([docs])
    hits = kb.search("How do I mute an incident in Acme?", k=3).results
    assert any("incidents.mdx" in h.chunk.metadata.get("path", "") for h in hits)
    assert kb.retriever()._discriminative("How do I mute an incident in Acme?").count("Acme") == 0
    kb.close()


def test_table_row_split_at_chunk_boundary_has_no_stray_pipes():
    from omnirag.generate.extractive import _prose_lines

    out = _prose_lines("Mutes this kind of incident on this source and column |")
    assert "|" not in out and "Mutes this kind of incident on this source and column" in out


def test_table_listing_only_shows_rows_meeting_every_condition(manager, tmp_path):
    folder = tmp_path / "orders"
    folder.mkdir()
    rows = ["order_id,region,status"]
    for i in range(60):
        region = ["north", "south"][i % 2]
        status = ["completed", "completed", "returned"][i % 3]
        rows.append(f"{1000 + i},{region},{status}")
    (folder / "orders.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    kb = manager.create("orders")
    kb.ingest([folder])
    text = kb.ask("Which orders are in the north region and returned?").text
    listed = [ln for ln in text.splitlines() if ln.startswith("- Row ")]
    assert listed, text
    assert all("region=north" in ln and "status=returned" in ln for ln in listed), text
    kb.close()
