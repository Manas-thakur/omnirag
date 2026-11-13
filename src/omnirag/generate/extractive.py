"""Offline extractive answerer.

Composes an answer from the most query-relevant sentences of the retrieved
sources, each followed by its ``[n]`` citation. No LLM is needed, so OmniRAG
is useful even on a machine with no model server at all.

Relevance is weighted by how rare each question word is in the knowledge base
(its BM25 IDF when the retriever provides one), so an answer must cover the
distinctive words of the question, not just a common one like "point" or
"level". Below that floor the answerer says it could not find an answer instead
of quoting loosely related sentences.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from omnirag.generate.citation import Source
from omnirag.query.parser import QueryIntent, detect_intent, detect_modality_hints
from omnirag.retrieve.context import context_header, path_words
from omnirag.store.models import Modality
from omnirag.textutil import (
    CHANGELOG_TERMS,
    VERSION_RE,
    is_change_question,
    mentions_version,
    split_sentences,
    terms,
    truncate,
)

_FENCE_BLOCK_RE = re.compile(r"```[\w+-]*\n(.*?)```", re.DOTALL)
_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)\s*$")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# A link cut in half at a chunk boundary: "MIT](https://img.shields.io/...)](LICENSE)".
_ORPHAN_LINK_RE = re.compile(r"^[^\[\]\n]*?\]\((?:[^()\s]|\([^)]*\))*\)")
_LEFTOVER_URL_RE = re.compile(r"\]\((?:[^()\s]|\([^)]*\))*\)")
_BADGE_RE = re.compile(r"shields\.io|/badge|badge\.svg|badgen\.net", re.IGNORECASE)
_IMAGE_LINE_RE = re.compile(r"^\s*(?:\(Image: (.+)\)|!\[([^\]]+)\]\([^)]*\))\s*$")
_IMAGE_LABEL_RE = re.compile(r"^(Caption|Alt text|Title|Description|Text in image):\s*")
_HEADER_RE = re.compile(
    r"^(Transcript of .*\]|Rows \d+-\d+ of table .*|[A-Z][a-z]+ (function|class|method|"
    r"interface|type|code) .*\(lines \d+-\d+\)|[A-Z][a-z]+ module \S+|Image: .*)$"
)
_BOX_CHARS_RE = re.compile(r"[─-▟■-◿]")
_LICENSE_RE = re.compile(
    r"(©|\(c\)\s*\d{4}|\bcopyright\b|\blicen[cs]ed under\b|^(MIT|Apache[- ]2\.0|BSD|GPL|ISC)"
    r"\b[^.]{0,40}$|\ball rights reserved\b)",
    re.IGNORECASE,
)
_LICENSE_Q_RE = re.compile(r"\b(licen[cs]e|copyright|author|owner)", re.IGNORECASE)
# Identifiers in a question (`code`, snake_case, camelCase, call() or module.attr()).
# PascalCase is left out: product names (AnomalyGuard) are written that way.
_IDENT_RE = re.compile(r"`[^`]+`|\b[a-z]+_[a-z0-9_]+\b|\b[a-z]+[A-Z]\w*\b|\b\w+\.\w+\(|\b\w+\(\)")
_NUMBER_Q_RE = re.compile(
    r"\b(how (long|many|much|often|big|large|fast|old)|when|what time|port|default|"
    r"limit|timeout|size|version)\b",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"</?(?:kbd|code|b|i|em|strong|br|span|sup|sub|small|mark|u|s)\b[^>]*>")
_LISTING_Q_RE = re.compile(r"\b(which|list|all|every|show)\b", re.IGNORECASE)
_CITE_LIKE_RE = re.compile(r"\[(\d)")

#: An answer must cover at least this share of the question's term weight.
RELEVANCE_FLOOR = 0.5
#: A sentence that shares no word with the question may still be quoted when
#: its section heading covers this much of the question (e.g. the bullets of a
#: changelog section named after the version asked about).
SECTION_FLOOR = 0.5

# Words that shape a question more than its topic ("how much", "what happens",
# "does it work"): they count like a word found everywhere, so a knowledge base
# that never uses them can still answer.
_SOFT_TERMS = frozenset(
    terms(
        "much many long often happen happens work works working improve improved mean means "
        "need needs want make makes take know look help differ difference affect handle "
        "handled cause matter keep way thing things possible example best good"
    )
)


def _aliases() -> dict[str, set[str]]:
    """Question term -> terms that answer for it (the retriever's synonyms)."""
    from omnirag.query.rewriter import SYNONYMS

    out: dict[str, set[str]] = {}
    for word, syns in SYNONYMS.items():
        for key in terms(word):
            out.setdefault(key, set()).update(t for syn in syns for t in terms(syn))
    return out


_ALIASES = _aliases()

NOT_FOUND = (
    "I couldn't find an answer to that in this knowledge base. "
    "The closest match is {label} (source {index}), but it doesn't "
    "mention what you asked about. Try rephrasing with terms from your "
    "documents, or add sources that cover this topic."
)


@dataclass
class TermWeights:
    """How much each question term counts: its IDF in the knowledge base.

    Terms that never occur in the knowledge base get the highest possible
    weight, so a question about something absent cannot be "answered" by
    sentences that only share its generic words.
    """

    idf: Mapping[str, float] | None = None
    documents: int = 0

    @property
    def unseen(self) -> float:
        if not self.idf:
            return 1.0
        n = max(self.documents, 1)
        return math.log(1 + (n + 0.5) / 0.5)

    def __call__(self, term: str) -> float:
        if not self.idf:
            return 1.0
        # Even a word found everywhere (a product name) still counts a little.
        return max(self.idf.get(term, self.unseen), 1.0)


@dataclass
class _Question:
    text: str
    terms: set[str]
    weights: dict[str, float]
    versions: list[str]
    about_changes: bool
    about_code: bool
    about_license: bool
    listing: bool
    #: Asks for a number: "how long", "how many", "which port", "default".
    wants_number: bool
    total: float = field(init=False)

    def __post_init__(self) -> None:
        self.total = sum(self.weights.values()) or 1.0

    def weight(self, matched: set[str]) -> float:
        return sum(self.weights[t] for t in matched)


def _question_terms(text: str) -> set[str]:
    """Question terms; a CamelCase name counts once, as itself ("AgentCore"
    must not match every sentence that says "agent")."""
    out: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9]+", text):
        found = terms(word)
        out.update(found[-1:] if len(found) > 1 else found)
    return out


def _analyse(question: str, weights: TermWeights) -> _Question:
    versions = VERSION_RE.findall(question)
    q_terms = _question_terms(VERSION_RE.sub(" ", question))
    w = {t: min(weights(t), 1.0) if t in _SOFT_TERMS else weights(t) for t in q_terms}
    if versions:
        # A version string is the most specific thing in the question.
        top = max([weights.unseen, *w.values()])
        for v in versions:
            w[f"v:{v}"] = top
    about_changes = is_change_question(question)
    return _Question(
        text=question,
        terms=set(w),
        weights=w,
        versions=versions,
        about_changes=about_changes,
        about_code=detect_intent(question) == QueryIntent.CODE or bool(_IDENT_RE.search(question)),
        about_license=bool(_LICENSE_Q_RE.search(question)),
        listing=bool(_LISTING_Q_RE.search(question)),
        wants_number=bool(_NUMBER_Q_RE.search(question)),
    )


def _term_set(text: str, q: _Question) -> set[str]:
    out = set(terms(text))
    # "decided" is answered by a sentence that says "decision".
    out |= {t for t in q.terms if t not in out and _ALIASES.get(t, set()) & out}
    for v in q.versions:
        if mentions_version(text, v):
            out.add(f"v:{v}")
    return out


def _heading_terms(src: Source, q: _Question) -> set[str]:
    head = " ".join(
        [
            context_header(src.metadata),
            str(src.metadata.get("heading", "")),
            str(src.title or ""),
            str(src.metadata.get("symbol", "")),
        ]
    )
    out = _term_set(head, q)
    if q.about_changes and out & CHANGELOG_TERMS:
        # "What changed in X?" is answered by a changelog / release notes page.
        out |= {t for t in q.terms if t.startswith("chang")}
    return out


# ------------------------------------------------------------------ cleanup
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


_ARROW_CELL_RE = re.compile(r"^\s*[-=~.]*[<>^v]?[-=~.]*[<>]+[-=~.]*\s*$")
_TABLE_RULE_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LINK_ONLY_RE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\([^)]*\)")


def _is_nav_line(line: str) -> bool:
    """Badge rows and link lists ("[Docs](..) · [Releases](..)") carry no prose."""
    if "](" not in line:
        return False
    rest = _LINK_ONLY_RE.sub("", line)
    rest = _LEFTOVER_URL_RE.sub("", _ORPHAN_LINK_RE.sub("", rest))
    return not re.sub(r"[\s·•|*_,/>\-\[\]!]+", "", rest)


def _is_diagram_line(line: str) -> bool:
    """ASCII art and box drawing: mostly symbols, few letters."""
    stripped = line.strip()
    if not stripped:
        return False
    if _BOX_CHARS_RE.search(stripped):
        return True
    if len(stripped) < 4:
        return False
    letters = sum(ch.isalnum() for ch in stripped)
    arrows = len(re.findall(r"-->|<--|==>|->|<-|\+-{2,}|-{3,}\+|\|\s{2,}\|", stripped))
    return letters / len(stripped) < 0.35 or arrows >= 2


def _table_row_sentence(line: str, headers: list[str] | None = None) -> str | None:
    """``| **Mute 24h** | Hides the incident |`` -> ``Mute 24h: Hides the incident``.

    With the table's header row, short column names label their cells:
    ``| --port | 8765 | Port |`` under ``Option | Default | Meaning`` becomes
    ``--port: default 8765; Port``.
    """
    if _TABLE_RULE_RE.match(line.strip()):
        return None
    raw = [c.strip().strip("*`").strip() for c in line.strip().strip("|").split("|")]
    raw = [c.replace("`", "") if c.count("`") % 2 else c for c in raw]
    labels = headers if headers and len(headers) == len(raw) else [""] * len(raw)
    cells = [(h, c) for h, c in zip(labels, raw, strict=True) if c]
    if len(cells) < 2:
        return cells[0][1] if cells else None

    def label(h: str, c: str) -> str:
        h = h.strip()
        if not h or h.lower() in _GENERIC_HEADERS or len(h.split()) > 2:
            return c
        return f"{h.lower()} {c}"

    return f"{cells[0][1]}: " + "; ".join(label(h, c) for h, c in cells[1:])


def _strip_code_fences(content: str) -> str:
    """Drop fenced code blocks, including halves cut off at a chunk boundary."""
    lines = content.splitlines()
    fences = [i for i, ln in enumerate(lines) if _FENCE_LINE_RE.match(ln)]
    if not fences:
        return content
    drop: set[int] = set()
    start = 0
    if len(fences) % 2 == 1:
        first = _FENCE_LINE_RE.match(lines[fences[0]])
        if first and not first.group(2) and any(ln.strip() for ln in lines[: fences[0]]):
            # The chunk starts inside a code block: everything up to the fence is code.
            drop.update(range(0, fences[0] + 1))
            start = 1
        else:
            fences.append(len(lines))  # an unclosed block runs to the end
    for a, b in zip(fences[start::2], fences[start + 1 :: 2], strict=False):
        drop.update(range(a, min(b, len(lines) - 1) + 1))
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


_GENERIC_HEADERS = frozenset(
    {"description", "meaning", "notes", "note", "details", "purpose", "what it does", "summary"}
)


def _is_row(line: str) -> bool:
    return line.count("|") >= 2 or line.startswith("|") or line.endswith("|")


def _prose_lines(content: str) -> str:
    out = []
    lines = content.splitlines()
    headers: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _is_nav_line(stripped):
            continue
        prev = lines[i - 1].strip() if i > 0 else ""
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if _is_row(stripped) and (
            # "| client | --> | api |" between "+------+" borders is a drawing, not a table.
            any(_ARROW_CELL_RE.match(c) for c in stripped.strip("|").split("|"))
            or (_is_diagram_line(prev) and not _TABLE_RULE_RE.match(prev))
            or (_is_diagram_line(nxt) and not _TABLE_RULE_RE.match(nxt))
        ):
            continue
        # Whole rows, and rows cut in half at a chunk boundary ("... text |").
        if _is_row(stripped):
            if _TABLE_RULE_RE.match(nxt) and not _TABLE_RULE_RE.match(stripped):
                # The header row names the columns; it is not an answer itself.
                headers = [c.strip().strip("*`").strip() for c in stripped.strip("|").split("|")]
                continue
            sentence = _table_row_sentence(stripped, headers)
            if sentence:
                # Its own paragraph so the sentence splitter keeps rows apart.
                out.extend(["", sentence.rstrip(".") + ".", ""])
            continue
        headers = []
        if _is_diagram_line(stripped):
            continue
        image = _IMAGE_LINE_RE.match(stripped)
        if image:
            # Alt text stays available, marked so it ranks below real prose.
            out.extend(["", "\x01" + (image.group(1) or image.group(2)).strip(), ""])
            continue
        out.append(line)
    return "\n".join(out)


@dataclass
class _Candidate:
    text: str
    src: Source
    pos: int
    alt: bool = False


def _candidates(src: Source, about_license: bool = False) -> list[_Candidate]:
    if src.modality == "code":
        return [_Candidate(s, src, i) for i, s in enumerate(_code_sentences(src))]
    content = src.content
    heading = str(src.metadata.get("heading", ""))
    if heading and content.startswith(heading):
        content = content[len(heading) :].lstrip()
    if src.modality == "text":
        # A badge or link cut in half at the chunk boundary ("MIT](https://...)").
        while m := _ORPHAN_LINK_RE.match(content):
            content = content[m.end() :].lstrip()
    fragment_start = src.modality == "text" and bool(re.match(r"[a-z,;:)\]}.]", content))
    if src.modality == "text":
        content = _prose_lines(_strip_code_fences(content))
    # Badges say nothing; other images keep their alt text.
    content = _MD_IMAGE_RE.sub(
        lambda m: "" if _BADGE_RE.search(m.group(0)) else m.group(1), content
    )
    content = _MD_LINK_RE.sub(lambda m: m.group(1), content)
    content = _LEFTOVER_URL_RE.sub("", content)
    content = content.replace("**", "")
    if src.modality == "text":
        content = _HTML_TAG_RE.sub("", content)
    if src.modality in {"image", "audio", "table"}:
        # Line-structured content: every line is its own unit.
        lines = content.splitlines()
        if src.modality == "image":
            lines = [
                _IMAGE_LABEL_RE.sub("", ln)
                for ln in lines
                if not ln.startswith(("File name:", "Dimensions:"))
            ]
        units = [s for line in lines for s in split_sentences(line)]
    else:
        units = split_sentences(content)
    out: list[_Candidate] = []
    for i, sent in enumerate(units):
        if i == 0 and fragment_start and not sent.startswith("\x01"):
            continue  # the tail of a sentence that began in the previous chunk
        alt = src.modality == "image" or sent.startswith("\x01")
        sent = re.sub(r"^[-*+]\s+", "", sent.lstrip("\x01")).strip()
        sent = _ORPHAN_LINK_RE.sub("", sent).strip()
        if not sent or _HEADER_RE.match(sent) or sent.startswith("|") or _is_nav_line(sent):
            continue
        if not about_license and _LICENSE_RE.search(sent):
            continue
        if _is_diagram_line(sent) or sent.startswith(("```", "~~~")):
            continue
        out.append(_Candidate(sent, src, i, alt))
    return out


def _candidate_sentences(src: Source) -> list[str]:
    """The quotable sentences of a source, in reading order."""
    return [c.text for c in _candidates(src)]


def _code_excerpt(src: Source, max_lines: int = 18) -> str | None:
    m = _FENCE_BLOCK_RE.search(src.content)
    if not m:
        return None
    lang = src.metadata.get("language", "")
    lines = m.group(1).rstrip("\n").splitlines()
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], "# ..." if lang == "python" else "// ..."]
    return f"```{lang}\n" + "\n".join(lines) + "\n```"


def _quote(text: str) -> str:
    """Keep bracketed numbers in quoted text from reading as citations."""
    return _CITE_LIKE_RE.sub("[⁠\\1", text)


_SUMMARY_RE = re.compile(
    r"\b(summari[sz]e|summary|overview|outline|describe|tl;?dr|tell me about|"
    r"what (?:does|do|is in) .+ (?:contain|show|cover|say|describe)|what is in)\b",
    re.IGNORECASE,
)


def is_summary_question(question: str) -> bool:
    """True for questions asking to summarise or describe a source as a whole."""
    return bool(_SUMMARY_RE.search(question))


def _doc_key(src: Source) -> str:
    return str(src.metadata.get("path") or src.label)


def _focus_document(question: str, sources: list[Source]) -> str:
    """Pick the document the question names (by path, file name or heading)."""
    q_terms = set(terms(question))
    best_key, best_score = _doc_key(sources[0]), 0.0
    for rank, src in enumerate(sources):
        name_terms = set(terms(f"{_doc_key(src)} {src.metadata.get('heading', '')} {src.label}"))
        score = len(q_terms & name_terms) - rank * 0.01
        if score > best_score:
            best_key, best_score = _doc_key(src), score
    return best_key


#: Looks up every row line of a table document (``"Row 7: status=returned, ..."``).
RowLookup = Callable[[str], list[str]]


@dataclass
class _Scored:
    score: float
    cand: _Candidate
    matched: set[str]
    #: Its section heading alone covers the question (e.g. "[0.3.0]" for
    #: "What changed in 0.3.0?"), so more of its sentences may be listed.
    in_section: bool = False


class ExtractiveAnswerer:
    def __init__(
        self,
        max_sentences: int = 6,
        per_source: int = 2,
        max_chars: int = 320,
        weights: TermWeights | None = None,
        table_rows: RowLookup | None = None,
    ) -> None:
        self.max_sentences = max_sentences
        self.per_source = per_source
        self.max_chars = max_chars
        self.weights = weights or TermWeights()
        self.table_rows = table_rows

    def summarize(self, question: str, sources: list[Source]) -> str | None:
        """Lead sentences of the document the question is about, in reading order."""
        focus = _focus_document(question, sources)
        lines: list[str] = []
        seen: set[str] = set()
        for src in sources:
            if _doc_key(src) != focus:
                continue
            for cand in _candidates(src):
                key = cand.text.lower()
                if cand.alt or len(terms(cand.text)) < 3 or key in seen:
                    continue
                seen.add(key)
                lines.append(f"- {_quote(truncate(cand.text, self.max_chars))} [{src.index}]")
                if len(lines) >= self.max_sentences:
                    return "\n".join(lines)
        return "\n".join(lines) if len(lines) >= 2 else None

    # ------------------------------------------------------------- scoring
    def _score_all(self, q: _Question, sources: list[Source]) -> list[_Scored]:
        scored: list[_Scored] = []
        # Question words that some sources are filed under and others are not
        # (a product or folder name in their path): a sentence from a source
        # that never mentions it probably talks about something else.
        filed = [set(terms(path_words(str(s.metadata.get("path") or "")))) for s in sources]
        scope = {
            t for t in q.terms if any(t in f for f in filed) and not all(t in f for f in filed)
        }
        # "What changed in 0.3.0?": when a changelog was retrieved, other pages
        # that merely mention the version are not the answer.
        changelogs = {
            s.index for s in sources if q.about_changes and _heading_terms(s, q) & CHANGELOG_TERMS
        }
        for rank, src in enumerate(sources):
            heading_terms = _heading_terms(src, q)
            head = heading_terms & q.terms
            context_terms = set(terms(path_words(str(src.metadata.get("path") or ""))))
            head_cov = q.weight(head) / q.total
            # A section named after the version asked about answers in full.
            head_factor = 1.0 if any(t.startswith("v:") for t in head) else 0.6
            for cand in _candidates(src, q.about_license):
                s_terms = _term_set(cand.text, q)
                own = s_terms & q.terms
                own_cov = q.weight(own) / q.total
                if not own and head_cov < SECTION_FLOOR:
                    continue
                n_terms = len(s_terms)
                if n_terms < 3 and own_cov < 0.5:
                    continue  # short and only loosely related
                extra = head - own
                relevance = own_cov + head_factor * q.weight(extra) / q.total
                # Prefer focused sentences over long ones that mention everything.
                length = 1.0 / (1.0 + 0.03 * max(0, n_terms - 14))
                # The section the question is about (its heading names the
                # question's words) beats a passing mention elsewhere.
                section = q.weight(head - context_terms) / q.total
                score = relevance * length + 0.15 * section + 0.12 / (rank + 1)
                if not own:
                    score -= 0.002 * cand.pos  # section-only matches: keep reading order
                if cand.alt:
                    score *= 0.5
                if cand.text.rstrip().endswith(":"):
                    score *= 0.3  # a lead-in to a list or code block, not an answer
                if q.wants_number and re.search(r"\d", cand.text):
                    score += 0.1
                if scope and not scope <= (s_terms | heading_terms):
                    score *= 0.5
                if changelogs and src.index not in changelogs:
                    score *= 0.3
                scored.append(_Scored(score, cand, own | head, head_cov >= SECTION_FLOOR))
        return scored

    def _covered(self, q: _Question, picked: list[_Scored]) -> float:
        matched: set[str] = set()
        for p in picked:
            matched |= p.matched
        return q.weight(matched) / q.total

    def answer(self, question: str, sources: list[Source], show_code: bool = True) -> str:
        if not sources:
            return "I could not find anything relevant in the knowledge base for that question."
        q = _analyse(question, self.weights)
        if is_summary_question(question):
            summary = self.summarize(question, sources)
            if summary:
                return summary
        scored = self._score_all(q, sources)
        # Image alt text only answers when no prose does, unless the question
        # asks for a picture ("show me the auth flow diagram").
        wants_image = Modality.IMAGE in detect_modality_hints(question)
        if not wants_image and any(not s.cand.alt for s in scored):
            prose_best = max(s.score for s in scored if not s.cand.alt)
            scored = [s for s in scored if not s.cand.alt or s.score > prose_best]
        scored.sort(key=lambda s: -s.score)
        picked: list[_Scored] = []
        per: dict[int, int] = {}
        seen: set[str] = set()
        best = scored[0].score if scored else 0.0
        for s in scored:
            src = s.cand.src
            limit = self.per_source
            if (src.modality == "table" and q.listing) or s.in_section:
                limit = 4
            key = s.cand.text.lower()
            if per.get(src.index, 0) >= limit or key in seen or s.score < 0.5 * best:
                continue
            picked.append(s)
            per[src.index] = per.get(src.index, 0) + 1
            seen.add(key)
            if len(picked) >= self.max_sentences:
                break
        picked = self._rows_meeting_condition(q, picked)
        if not picked or self._covered(q, picked) < RELEVANCE_FLOOR:
            top = sources[0]
            return NOT_FOUND.format(label=top.label, index=top.index)
        picked.sort(key=lambda s: (s.cand.src.index, s.cand.pos))
        lines = [
            f"- {_quote(truncate(s.cand.text, self.max_chars))} [{s.cand.src.index}]"
            for s in picked
        ]
        text = "\n".join(lines)
        note = self._partial_rows_note(q, picked)
        if note:
            text += "\n\n" + note
        if show_code and self._wants_code(q, sources):
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

    @staticmethod
    def _wants_code(q: _Question, sources: list[Source]) -> bool:
        """Only show code when the question is about code."""
        if q.about_code or all(s.modality == "code" for s in sources):
            return True
        words = {w.lower() for w in re.findall(r"\w+", q.text)}
        return any(
            str(s.metadata.get("symbol", "")).lower() in words
            for s in sources
            if s.modality == "code" and s.metadata.get("symbol")
        )

    def _rows_meeting_condition(self, q: _Question, picked: list[_Scored]) -> list[_Scored]:
        """Drop table rows that don't meet the condition a listing question asks about.

        For "Which orders have status returned?" the condition is the question's
        words that appear in only some of the table's rows ("returned"); words in
        (nearly) every row ("orders", "status") are column names. A listed row
        that lacks a condition word another listed row has is a near miss
        (e.g. ``status=completed``) and must not be presented as a match.
        """
        if not q.listing:
            return picked
        by_doc: dict[str, list[_Scored]] = {}
        for s in picked:
            if s.cand.src.modality == "table" and s.cand.text.startswith("Row "):
                by_doc.setdefault(s.cand.src.doc_id, []).append(s)
        drop: set[int] = set()
        for doc_id, rows in by_doc.items():
            src = rows[0].cand.src
            all_rows = self.table_rows(doc_id) if self.table_rows else []
            if not all_rows:
                all_rows = [ln for ln in src.content.splitlines() if ln.startswith("Row ")]
            row_terms = [_term_set(r, q) & q.terms for r in all_rows]
            if not row_terms:
                continue
            counts = {t: sum(t in rt for rt in row_terms) for t in q.terms}
            # Condition words: values found in some rows but not (nearly) all.
            condition = {t for t, c in counts.items() if 0 < c <= 0.8 * len(row_terms)}
            condition -= _heading_terms(src, q)
            if not condition:
                continue
            kept = [s for s in rows if condition <= (s.matched | _term_set(s.cand.text, q))]
            for s in rows:
                if s not in kept:
                    drop.add(id(s))
            if not kept:
                # None of the retrieved rows qualify; read matching rows from the
                # whole table instead of presenting near misses.
                extra = [r for r, rt in zip(all_rows, row_terms, strict=True) if condition <= rt]
                template = rows[0]
                for pos, line in enumerate(extra[:4]):
                    cand = dataclasses.replace(template.cand, text=line, pos=pos)
                    picked.append(
                        dataclasses.replace(
                            template, cand=cand, matched=condition | template.matched
                        )
                    )
        return [s for s in picked if id(s) not in drop]

    def _partial_rows_note(self, q: _Question, picked: list[_Scored]) -> str | None:
        """'Showing 2 of 54 matching rows' when a table has more rows like the ones listed."""
        by_doc: dict[str, list[_Scored]] = {}
        for s in picked:
            if s.cand.src.modality == "table" and s.cand.text.startswith("Row "):
                by_doc.setdefault(s.cand.src.doc_id, []).append(s)
        notes = []
        for doc_id, rows in by_doc.items():
            src = rows[0].cand.src
            all_rows = self.table_rows(doc_id) if self.table_rows else []
            if not all_rows:
                all_rows = [ln for ln in src.content.splitlines() if ln.startswith("Row ")]
            row_terms = [_term_set(r, q) & q.terms for r in all_rows]
            if not row_terms:
                continue
            # Terms in (nearly) every row are column names, not the condition asked about.
            common = {t for t in q.terms if sum(t in rt for rt in row_terms) > 0.8 * len(row_terms)}
            wanted = set.intersection(*(s.matched & q.terms for s in rows)) - common
            wanted -= _heading_terms(src, q)
            if not wanted:
                continue
            matching = sum(wanted <= rt for rt in row_terms)
            shown = len(rows)
            if matching > shown:
                name = src.metadata.get("path") or src.label
                notes.append(
                    f"Showing {shown} of {matching} matching rows in {name} [{src.index}]."
                )
        return " ".join(notes) or None
