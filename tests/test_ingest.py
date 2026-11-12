from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from omnirag.config import Settings
from omnirag.ingest import (
    AudioIngestor,
    CodeIngestor,
    ImageIngestor,
    IngestContext,
    IngestError,
    IngestionPipeline,
    TableIngestor,
    TextIngestor,
    collect_alt_texts,
    detect_language,
    detect_modality,
    discover,
    html_to_text,
    is_sidecar,
    parse_subtitles,
)
from omnirag.ingest.image import png_metadata, svg_text
from omnirag.store.models import Modality


def ctx(root: Path | None = None, **kw) -> IngestContext:
    return IngestContext(settings=Settings(home=Path(".")), root=root, **kw)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.md", Modality.TEXT),
        ("a.pdf", Modality.TEXT),
        ("a.html", Modality.TEXT),
        ("a.PNG", Modality.IMAGE),
        ("a.svg", Modality.IMAGE),
        ("a.mp3", Modality.AUDIO),
        ("a.vtt", Modality.AUDIO),
        ("a.py", Modality.CODE),
        ("a.tsx", Modality.CODE),
        ("a.csv", Modality.TABLE),
        ("a.jsonl", Modality.TABLE),
        ("a.exe", None),
    ],
)
def test_detect_modality(name, expected):
    assert detect_modality(name) == expected


def test_detect_language_and_shebang(tmp_path):
    script = tmp_path / "tool"
    script.write_text("#!/usr/bin/env python3\nprint('hi')\n")
    assert detect_modality(script) == Modality.CODE
    assert detect_language(script) == "python"
    assert detect_language("x.ts") == "typescript"


def test_markdown_ingest_keeps_headings_and_front_matter(tmp_path):
    md = tmp_path / "guide.md"
    md.write_text(
        "---\ntitle: The Guide\nauthor: Ada\n---\n# Intro\nHello world.\n\n## Setup\nRun the installer.\n"
    )
    doc = TextIngestor().ingest(md, ctx())
    assert doc.title == "The Guide"
    assert doc.metadata["author"] == "Ada"
    assert [c.metadata.get("heading") for c in doc.chunks] == ["Intro", "Intro > Setup"]
    assert doc.chunks[1].content.startswith("Intro > Setup")


def test_html_to_text_strips_scripts_and_keeps_structure():
    text, title, images = html_to_text(
        "<html><head><title>T</title><script>evil()</script></head><body>"
        "<h1>Head</h1><p>Para <b>bold</b>.</p><img src='x.png' alt='An X'></body></html>"
    )
    assert title == "T"
    assert "# Head" in text and "Para bold." in text
    assert "evil" not in text
    assert images == [("x.png", "An X")]


def test_rst_and_txt(tmp_path):
    rst = tmp_path / "doc.rst"
    rst.write_text("Title\n=====\n\nBody text here.\n\nSub\n---\n\nMore text.\n")
    doc = TextIngestor().ingest(rst, ctx())
    assert [c.metadata["section"] for c in doc.chunks] == ["Title", "Sub"]
    txt = tmp_path / "notes.txt"
    txt.write_text("word " * 1000)
    doc = TextIngestor().ingest(txt, ctx(chunk_size=500, chunk_overlap=50))
    assert len(doc.chunks) > 5


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


def test_pdf_ingest(tmp_path):
    pytest.importorskip("pypdf")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(_minimal_pdf("Quantum widgets improve throughput"))
    doc = TextIngestor().ingest(pdf, ctx())
    assert doc.metadata["pages"] == 1
    assert "Quantum widgets" in doc.chunks[0].content
    assert doc.chunks[0].metadata["page"] == 1


def test_python_code_ingest(corpus):
    doc = CodeIngestor().ingest(corpus / "src" / "rate_limiter.py", ctx(corpus))
    kinds = {c.metadata.get("symbol"): c.metadata["kind"] for c in doc.chunks}
    assert kinds["TokenBucket"] == "class"
    assert kinds["RateLimiter"] == "class"
    assert doc.metadata["language"] == "python"
    bucket = next(c for c in doc.chunks if c.metadata.get("symbol") == "TokenBucket")
    assert "Documentation: A token bucket" in bucket.content
    assert "```python" in bucket.content
    assert bucket.metadata["line_start"] < bucket.metadata["line_end"]


def test_large_python_class_is_split_into_methods(tmp_path):
    methods = "\n".join(
        f"    def m{i}(self):\n        '''Method {i}.'''\n" + "        x = 1\n" * 8
        for i in range(10)
    )
    src = tmp_path / "big.py"
    src.write_text(f"class Big:\n    '''A big class.'''\n{methods}")
    doc = CodeIngestor().ingest(src, ctx())
    symbols = [c.metadata.get("symbol") for c in doc.chunks]
    assert "Big.m0" in symbols and "Big.m9" in symbols


def test_python_syntax_error_falls_back(tmp_path):
    src = tmp_path / "broken.py"
    src.write_text("def oops(:\n    pass\n" + "x = 1\n" * 10)
    doc = CodeIngestor().ingest(src, ctx())
    assert doc.warnings and doc.chunks


def test_typescript_code_ingest(corpus):
    doc = CodeIngestor().ingest(corpus / "src" / "auth_middleware.ts", ctx(corpus))
    by_symbol = {c.metadata.get("symbol"): c for c in doc.chunks}
    assert "authMiddleware" in by_symbol and "requireRole" in by_symbol
    assert "validates the JWT" in by_symbol["authMiddleware"].content
    assert "AuthenticatedRequest" in by_symbol


def test_other_language_line_chunks(tmp_path):
    go = tmp_path / "main.go"
    go.write_text("package main\n\n" + "\n".join(f"// line {i}" for i in range(150)))
    doc = CodeIngestor().ingest(go, ctx())
    assert doc.metadata["language"] == "go"
    assert len(doc.chunks) >= 2


def test_csv_table_summary_and_rows(corpus):
    doc = TableIngestor().ingest(corpus / "data" / "latency_benchmarks.csv", ctx(corpus))
    summary = doc.chunks[0]
    assert summary.metadata["kind"] == "summary"
    assert "8 rows, 8 columns" in summary.content
    assert "p95_ms (integer): min 38, max 310" in summary.content
    assert "cache=redis" in doc.chunks[1].content


def test_json_and_jsonl_tables(tmp_path):
    j = tmp_path / "items.json"
    j.write_text('{"items": [{"name": "a", "price": 1.5}, {"name": "b", "price": 2.5}]}')
    doc = TableIngestor().ingest(j, ctx())
    assert doc.metadata["rows"] == 2
    assert "price (float)" in doc.chunks[0].content
    jl = tmp_path / "events.jsonl"
    jl.write_text('{"event": "login"}\n{"event": "logout"}\n')
    assert TableIngestor().ingest(jl, ctx()).metadata["rows"] == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(IngestError):
        TableIngestor().ingest(bad, ctx())


def test_svg_metadata(corpus):
    info = svg_text(corpus / "diagrams" / "auth-flow.svg")
    assert info["title"] == "JWT authentication flow"
    assert "Sequence diagram" in info["description"]
    assert "Auth service" in info["text"]


def _png_with_text(path: Path, text: dict[str, str]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 4 for _ in range(3))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
    for k, v in text.items():
        data += chunk(b"tEXt", k.encode() + b"\x00" + v.encode())
    data += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def test_png_metadata_and_sidecar(tmp_path):
    img = tmp_path / "chart-q3.png"
    _png_with_text(img, {"Title": "Quarterly revenue"})
    info = png_metadata(img)
    assert info["dimensions"] == "4x3"
    assert info["text_chunks"]["Title"] == "Quarterly revenue"

    doc = ImageIngestor().ingest(img, ctx(tmp_path))
    assert doc.title == "Quarterly revenue"
    assert "embedded-metadata" in doc.metadata["description_sources"]

    (tmp_path / "chart-q3.png.txt").write_text("Bar chart of Q3 revenue by region")
    doc = ImageIngestor().ingest(img, ctx(tmp_path))
    assert "Bar chart of Q3 revenue" in doc.chunks[0].content
    assert doc.metadata["description_sources"][0] == "sidecar"


def test_image_falls_back_to_filename(tmp_path):
    img = tmp_path / "network_topology-v2.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0not-really-a-jpeg")
    doc = ImageIngestor().ingest(img, ctx())
    assert "network topology v2" in doc.chunks[0].content
    assert doc.warnings


def test_image_alt_text_from_markdown(corpus):
    files = discover([corpus])
    alts = collect_alt_texts(files)
    svg = str((corpus / "diagrams" / "auth-flow.svg").resolve())
    assert any("Authentication flow diagram" in a for a in alts[svg])
    doc = ImageIngestor().ingest(corpus / "diagrams" / "auth-flow.svg", ctx(corpus, alt_texts=alts))
    assert "Alt text: Authentication flow diagram" in doc.chunks[0].content


def test_vtt_parsing_with_speakers(corpus):
    cues = parse_subtitles((corpus / "meetings" / "architecture-review-2026-05-15.vtt").read_text())
    assert len(cues) == 8
    assert cues[0].speaker == "Priya" and cues[0].start == 5.0
    assert "two-phase" in cues[1].text


def test_srt_parsing_and_speaker_prefix():
    srt = "1\n00:00:01,000 --> 00:00:03,500\nBob: Hello there\n\n2\n00:01:00,000 --> 00:01:02,000\nGeneral remark\n"
    cues = parse_subtitles(srt)
    assert cues[0].speaker == "Bob" and cues[0].text == "Hello there"
    assert cues[1].start == 60.0 and cues[1].speaker is None


def test_audio_transcript_ingest(corpus):
    doc = AudioIngestor().ingest(
        corpus / "meetings" / "architecture-review-2026-05-15.vtt", ctx(corpus)
    )
    assert doc.title == "Architecture Review Meeting 2026-05-15"
    assert doc.metadata["speakers"] == ["Priya", "Marco", "Aisha"]
    first = doc.chunks[0]
    assert first.metadata["start"] == 5.0
    assert "[00:15] Marco:" in first.content


def test_audio_uses_sidecar_transcript_or_metadata(tmp_path):
    audio = tmp_path / "standup.mp3"
    audio.write_bytes(b"ID3fake")
    (tmp_path / "standup.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nAlice: Shipping today\n"
    )
    doc = AudioIngestor().ingest(audio, ctx())
    assert "Alice: Shipping today" in doc.chunks[0].content
    assert doc.metadata["transcript_source"] == "standup.srt"

    lonely = tmp_path / "lonely.wav"
    lonely.write_bytes(b"RIFF")
    doc = AudioIngestor().ingest(lonely, ctx())
    assert "No transcript available" in doc.chunks[0].content


def test_discover_skips_sidecars_hidden_and_unsupported(tmp_path, corpus):
    (tmp_path / "talk.mp3").write_bytes(b"x")
    (tmp_path / "talk.vtt").write_text("WEBVTT\n")
    (tmp_path / "img.png").write_bytes(b"x")
    (tmp_path / "img.caption.txt").write_text("caption")
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "binary.exe").write_bytes(b"\x00\x01")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.md").write_text("# no")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("x")
    names = sorted(p.name for p in discover([tmp_path]))
    assert names == ["img.png", "readme.txt", "talk.mp3"]
    assert is_sidecar(tmp_path / "talk.vtt")
    assert not is_sidecar(tmp_path / "readme.txt")
    corpus_names = {p.name for p in discover([corpus])}
    assert "deployment-topology.png.txt" not in corpus_names
    assert "deployment-topology.png" in corpus_names


def test_discover_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover([tmp_path / "nope"])


def test_pipeline_parses_whole_corpus(corpus):
    pipe = IngestionPipeline(ctx())
    files = pipe.prepare([corpus])
    modalities = {pipe.parse(f).modality for f in files}
    assert modalities == set(Modality)
