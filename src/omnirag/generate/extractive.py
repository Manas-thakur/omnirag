"""Offline extractive answerer.

Composes an answer from the most query-relevant sentences of the retrieved
sources, each followed by its ``[n]`` citation. No LLM is needed, so OmniRAG
is useful even on a machine with no model server at all.
"""

from __future__ import annotations

import math
import re

from omnirag.generate.citation import Source
from omnirag.textutil import split_sentences, terms, truncate

_FENCE_BLOCK_RE = re.compile(r"```[\w+-]*\n(.*?)```", re.DOTALL)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMAGE_LABEL_RE = re.compile(r"^(Caption|Alt text|Title|Description|Text in image):\s*")
_HEADER_RE = re.compile(
    r"^(Transcript of .*\]|Rows \d+-\d+ of table .*|[A-Z][a-z]+ (function|class|method|"
    r"interface|type|code) .*\(lines \d+-\d+\)|[A-Z][a-z]+ module \S+|Image: .*)$"
)


def _code_sentences(src: Source) -> list[str]:
    prose = _FENCE_BLOCK_RE.sub("", src.content)
    symbol = src.metadata.get("symbol")
    kind = src.metadata.get("kind")
    signature = ""
    doc_lines: list[str] = []
    other: list[str] = []
    in_doc = False
    for line in prose.splitlines():
        stripped = line.strip()
        if stripped.startswith("Signature:"):
            signature = stripped.split(":", 1)[1].strip()
            in_doc = False
        elif stripped.startswith("Documentation:"):
            doc_lines.append(stripped.split(":", 1)[1].strip())
            in_doc = True
        elif in_doc:
            doc_lines.append(stripped)
        elif stripped.startswith("Defines:"):
            other.append(f"{src.metadata.get('path', src.label)} defines {stripped[8:].strip()}.")
        elif stripped and not _HEADER_RE.match(stripped):
            other.append(stripped)
    doc = " ".join(d for d in doc_lines if d)
    sentences = split_sentences(doc) if doc else []
    if sentences and symbol and kind in {"function", "class", "method", "interface", "type"}:
        sentences[0] = f"`{symbol}` ({kind}): {sentences[0]}"
    elif not sentences and signature and kind in {"function", "method"}:
        sentences = [f"`{signature}`"]
    return sentences + [s for line in other for s in split_sentences(line)]


def _candidate_sentences(src: Source) -> list[str]:
    if src.modality == "code":
        return _code_sentences(src)
    content = src.content
    heading = str(src.metadata.get("heading", ""))
    if heading and content.startswith(heading):
        content = content[len(heading) :].lstrip()
    content = _MD_IMAGE_RE.sub(lambda m: m.group(1), content)
    content = _MD_LINK_RE.sub(lambda m: m.group(1), content)
    content = content.replace("**", "")
    if src.modality in {"image", "audio", "table"}:
        # Line-structured content: every line is its own unit.
        lines = content.splitlines()
        if src.modality == "image":
            lines = [_IMAGE_LABEL_RE.sub("", ln) for ln in lines if not ln.startswith("File name:")]
        units = [s for line in lines for s in split_sentences(line)]
    else:
        units = split_sentences(content)
    sentences = []
    for sent in units:
        sent = sent.lstrip("-*+ ").strip()
        if not sent or _HEADER_RE.match(sent) or sent.startswith("|"):
            continue
        sentences.append(sent)
    return sentences


def _code_excerpt(src: Source, max_lines: int = 18) -> str | None:
    m = _FENCE_BLOCK_RE.search(src.content)
    if not m:
        return None
    lang = src.metadata.get("language", "")
    lines = m.group(1).rstrip("\n").splitlines()
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], "# ..." if lang == "python" else "// ..."]
    return f"```{lang}\n" + "\n".join(lines) + "\n```"


class ExtractiveAnswerer:
    def __init__(self, max_sentences: int = 6, per_source: int = 2, max_chars: int = 320) -> None:
        self.max_sentences = max_sentences
        self.per_source = per_source
        self.max_chars = max_chars

    def answer(self, question: str, sources: list[Source], show_code: bool = True) -> str:
        if not sources:
            return "I could not find anything relevant in the knowledge base for that question."
        q_terms = set(terms(question))
        scored: list[tuple[float, int, int, str]] = []
        for rank, src in enumerate(sources):
            for pos, sent in enumerate(_candidate_sentences(src)):
                s_terms = terms(sent)
                if len(s_terms) < 3:
                    continue
                overlap = len(q_terms & set(s_terms))
                if overlap == 0:
                    continue
                score = overlap / math.sqrt(len(set(s_terms))) + 0.6 / (rank + 1)
                scored.append((score, src.index, pos, sent))
        scored.sort(key=lambda x: -x[0])
        picked: list[tuple[int, int, str]] = []
        per: dict[int, int] = {}
        seen: set[str] = set()
        for _score, idx, pos, sent in scored:
            key = sent.lower()
            if per.get(idx, 0) >= self.per_source or key in seen:
                continue
            picked.append((idx, pos, sent))
            per[idx] = per.get(idx, 0) + 1
            seen.add(key)
            if len(picked) >= self.max_sentences:
                break
        if not picked:
            top = sources[0]
            return (
                "No source matches the question closely. The closest match is "
                f"{top.label}: {truncate(top.content, self.max_chars)} [{top.index}]"
            )
        picked.sort(key=lambda x: (x[0], x[1]))
        lines = []
        for idx, _pos, sent in picked:
            lines.append(f"- {truncate(sent, self.max_chars)} [{idx}]")
        text = "\n".join(lines)
        if show_code:
            code_src = next(
                (
                    s
                    for s in sources
                    if s.modality == "code" and s.index in per and "```" in s.content
                ),
                None,
            )
            if code_src is not None:
                excerpt = _code_excerpt(code_src)
                if excerpt:
                    text += (
                        f"\n\nRelevant code from {code_src.label} [{code_src.index}]:\n{excerpt}"
                    )
        return text
