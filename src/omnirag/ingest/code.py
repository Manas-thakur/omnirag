"""Source code: Python via the ``ast`` module, JavaScript/TypeScript via regex,
everything else via overlapping line windows.

Each chunk carries a short natural-language header (kind, name, signature,
docstring) followed by the code itself, so both keyword and semantic search can
find it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from omnirag.chunking import RawChunk, chunk_lines
from omnirag.ingest.base import IngestContext, Ingestor, ParsedDocument, read_text_file
from omnirag.ingest.detector import detect_language
from omnirag.store.models import Modality

MAX_CODE_LINES = 80


@dataclass
class _Symbol:
    kind: str  # function | class | method | module
    name: str
    signature: str
    doc: str
    start: int  # 1-based inclusive
    end: int
    parent: str | None = None


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:  # pragma: no cover - defensive
        args = ", ".join(a.arg for a in node.args.args)
    ret = ""
    if node.returns is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:  # pragma: no cover
            ret = ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){ret}"


def _python_symbols(source: str) -> tuple[str, list[_Symbol]]:
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree) or ""
    symbols: list[_Symbol] = []

    def start_of(node: ast.AST) -> int:
        decos = getattr(node, "decorator_list", [])
        return min([node.lineno] + [d.lineno for d in decos])  # type: ignore[attr-defined]

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                _Symbol(
                    "function",
                    node.name,
                    _python_signature(node),
                    ast.get_docstring(node) or "",
                    start_of(node),
                    node.end_lineno or node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            methods = [
                n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            end = node.end_lineno or node.lineno
            sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
            symbols.append(
                _Symbol(
                    "class",
                    node.name,
                    sig,
                    ast.get_docstring(node) or "",
                    start_of(node),
                    end,
                )
            )
            if end - start_of(node) + 1 > MAX_CODE_LINES:
                for m in methods:
                    symbols.append(
                        _Symbol(
                            "method",
                            f"{node.name}.{m.name}",
                            _python_signature(m),
                            ast.get_docstring(m) or "",
                            start_of(m),
                            m.end_lineno or m.lineno,
                            parent=node.name,
                        )
                    )
    return module_doc, symbols


_JS_PATTERNS = [
    (
        "class",
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*[(<]"
        ),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>"
        ),
    ),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*=")),
]


def _js_leading_comment(lines: list[str], idx: int) -> tuple[str, int]:
    """Collect a JSDoc / line-comment block directly above line ``idx`` (0-based)."""
    j = idx - 1
    collected: list[str] = []
    while j >= 0 and lines[j].strip().startswith(("//", "*", "/*", "*/")):
        collected.append(lines[j])
        j -= 1
    collected.reverse()
    doc = []
    for line in collected:
        s = line.strip().strip("/*").strip()
        if s and not s.startswith("@"):
            doc.append(s)
    return " ".join(doc), j + 1


def _js_symbols(source: str) -> list[_Symbol]:
    lines = source.splitlines()
    starts: list[tuple[int, str, str, str, int]] = []
    for i, line in enumerate(lines):
        # Only consider top-level-ish declarations (indent <= 2 spaces).
        if len(line) - len(line.lstrip()) > 2:
            continue
        for kind, pattern in _JS_PATTERNS:
            m = pattern.match(line)
            if m:
                doc, doc_start = _js_leading_comment(lines, i)
                starts.append((i, kind, m.group(1), doc, doc_start))
                break
    symbols = []
    for n, (i, kind, name, doc, doc_start) in enumerate(starts):
        nxt = starts[n + 1][4] if n + 1 < len(starts) else len(lines)
        end = nxt
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        symbols.append(
            _Symbol(kind, name, lines[i].strip().rstrip("{").strip(), doc, doc_start + 1, end)
        )
    return symbols


class CodeIngestor(Ingestor):
    modality = Modality.CODE

    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        source = read_text_file(path)
        language = detect_language(path) or path.suffix.lstrip(".") or "text"
        rel = ctx.display_path(path)
        lines = source.splitlines()
        warnings: list[str] = []
        module_doc = ""
        symbols: list[_Symbol] = []
        if language == "python":
            try:
                module_doc, symbols = _python_symbols(source)
            except SyntaxError as exc:
                warnings.append(f"python parse failed ({exc.msg}); fell back to line chunks")
        elif language in {"javascript", "typescript"}:
            symbols = _js_symbols(source)

        chunks: list[RawChunk] = []
        covered: set[int] = set()
        names = [s.name for s in symbols if s.kind != "method"]
        if module_doc or names:
            summary = [f"{language.title()} module {rel}"]
            if module_doc:
                summary.append(module_doc.strip())
            if names:
                summary.append("Defines: " + ", ".join(names))
            chunks.append(
                RawChunk(
                    "\n".join(summary),
                    {"symbol": path.stem, "kind": "module", "language": language},
                )
            )
        for sym in symbols:
            if sym.kind == "class" and any(s.parent == sym.name for s in symbols):
                # Large class: summarise the header; methods get their own chunks.
                body_end = min(sym.end, sym.start + 15)
            else:
                body_end = sym.end
            covered.update(range(sym.start, sym.end + 1))
            for first, last, code in chunk_lines(
                lines[sym.start - 1 : body_end], MAX_CODE_LINES, 5, sym.start
            ):
                header = [
                    f"{language.title()} {sym.kind} `{sym.name}` in {rel} (lines {first}-{last})"
                ]
                header.append(f"Signature: {sym.signature}")
                if sym.doc:
                    header.append(f"Documentation: {sym.doc.strip()}")
                content = "\n".join(header) + f"\n```{language}\n{code}\n```"
                meta = {
                    "symbol": sym.name,
                    "kind": sym.kind,
                    "language": language,
                    "line_start": first,
                    "line_end": last,
                }
                chunks.append(RawChunk(content, meta))

        # Anything not covered by a symbol (scripts, top-level statements, other languages).
        uncovered: list[tuple[int, str]] = [
            (i + 1, line) for i, line in enumerate(lines) if (i + 1) not in covered
        ]
        meaningful = [
            ln
            for _, ln in uncovered
            if ln.strip() and not ln.strip().startswith(("import ", "from "))
        ]
        if uncovered and (not symbols or len(meaningful) >= 5):
            for block in _contiguous(uncovered):
                start = block[0][0]
                for first, last, code in chunk_lines(
                    [ln for _, ln in block], MAX_CODE_LINES, 5, start
                ):
                    if not code.strip():
                        continue
                    content = (
                        f"{language.title()} code in {rel} (lines {first}-{last})\n"
                        f"```{language}\n{code}\n```"
                    )
                    chunks.append(
                        RawChunk(
                            content,
                            {
                                "kind": "block",
                                "language": language,
                                "line_start": first,
                                "line_end": last,
                            },
                        )
                    )
        chunks.sort(key=lambda c: c.metadata.get("line_start", 0))
        return ParsedDocument(
            path,
            Modality.CODE,
            rel,
            chunks,
            {"language": language, "lines": len(lines), "symbols": names},
            warnings,
        )


def _contiguous(numbered: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    for item in numbered:
        if blocks and item[0] == blocks[-1][-1][0] + 1:
            blocks[-1].append(item)
        else:
            blocks.append([item])
    return blocks
