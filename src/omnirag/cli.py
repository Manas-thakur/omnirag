"""``omnirag`` command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from omnirag import __version__
from omnirag.config import Settings
from omnirag.generate.llm import LLMError
from omnirag.index import IndexManager, KnowledgeBaseError
from omnirag.retrieve.retriever import MODES
from omnirag.store.models import Modality, SearchFilters

app = typer.Typer(
    name="omnirag",
    help="OmniRAG - multi-modal RAG knowledge assistant (text, code, tables, images, audio).",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
kb_app = typer.Typer(help="Create, list, rebuild and delete knowledge bases.", no_args_is_help=True)
app.add_typer(kb_app, name="kb")

console = Console()
err = Console(stderr=True)


class _State:
    home: Path | None = None


state = _State()

KB_OPTION = typer.Option("default", "--kb", "-b", help="Knowledge base name.", envvar="OMNIRAG_KB")


def _manager() -> IndexManager:
    return IndexManager(state.home, Settings.from_env())


def _fail(message: str, code: int = 1) -> None:
    err.print(f"[bold red]error:[/] {message}")
    raise typer.Exit(code)


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _version(value: bool) -> None:
    if value:
        console.print(f"omnirag {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="Where knowledge bases live (default: $OMNIRAG_HOME or ~/.omnirag).",
        envvar="OMNIRAG_HOME",
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show version and exit."
    ),
) -> None:
    state.home = data_dir


# --------------------------------------------------------------------------- kb
@kb_app.command("create")
def kb_create(
    name: str = typer.Argument(..., help="Knowledge base name."),
    description: str = typer.Option("", "--description", help="Free-form description."),
    embedder: str | None = typer.Option(
        None,
        "--embedder",
        "-e",
        help="hashing[:dim] (default), st:<hf-model> or ollama:<model>.",
    ),
) -> None:
    """Create a new knowledge base."""
    try:
        kb = _manager().create(name, description, embedder)
    except KnowledgeBaseError as exc:
        _fail(str(exc))
        return
    console.print(f"Created knowledge base [bold]{name}[/] (embedder: {kb.config.embedder})")
    console.print(f"  location: {kb.path}")
    kb.close()


@kb_app.command("list")
def kb_list() -> None:
    """List knowledge bases."""
    mgr = _manager()
    configs = mgr.list()
    if not configs:
        console.print(f"No knowledge bases in {mgr.root}. Create one with: omnirag kb create NAME")
        return
    table = Table(title=f"Knowledge bases in {mgr.root}")
    for col in ("name", "documents", "chunks", "embedder", "description"):
        table.add_column(col)
    for cfg in configs:
        with mgr.get(cfg.name) as kb:
            s = kb.store.stats()
        table.add_row(cfg.name, str(s.documents), str(s.chunks), cfg.embedder, cfg.description)
    console.print(table)


@kb_app.command("delete")
def kb_delete(
    name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Delete a knowledge base and all of its data (source files are not touched)."""
    mgr = _manager()
    if not mgr.exists(name):
        _fail(f"knowledge base {name!r} does not exist")
    if not yes:
        typer.confirm(f"Delete knowledge base {name!r} and its index?", abort=True)
    mgr.delete(name)
    console.print(f"Deleted knowledge base [bold]{name}[/]")


@kb_app.command("rebuild")
def kb_rebuild(
    name: str = typer.Argument(...),
    embedder: str | None = typer.Option(
        None, "--embedder", "-e", help="Switch to a different embedder before rebuilding."
    ),
) -> None:
    """Re-embed all chunks (e.g. after changing the embedder)."""
    try:
        with _manager().get(name) as kb:
            n = kb.rebuild(embedder)
            console.print(f"Re-embedded {n} chunks with {kb.config.embedder}")
    except KnowledgeBaseError as exc:
        _fail(str(exc))


@kb_app.command("prune")
def kb_prune(name: str = typer.Argument(...)) -> None:
    """Remove documents whose source files no longer exist."""
    try:
        with _manager().get(name) as kb:
            removed = kb.prune()
    except KnowledgeBaseError as exc:
        _fail(str(exc))
        return
    console.print(f"Removed {len(removed)} missing document(s)")
    for src in removed:
        console.print(f"  - {src}")


# ----------------------------------------------------------------------- ingest
@app.command()
def ingest(
    paths: list[Path] = typer.Argument(..., help="Files and/or directories to ingest."),
    kb_name: str = KB_OPTION,
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Recurse into dirs."),
    force: bool = typer.Option(False, "--force", help="Re-ingest even unchanged files."),
    create: bool = typer.Option(True, "--create/--no-create", help="Create the KB if missing."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print the summary."),
) -> None:
    """Ingest files into a knowledge base (incremental: unchanged files are skipped)."""
    mgr = _manager()
    try:
        if not mgr.exists(kb_name):
            if not create:
                _fail(f"knowledge base {kb_name!r} does not exist")
            mgr.create(kb_name).close()
            console.print(f"Created knowledge base [bold]{kb_name}[/]")
        kb = mgr.get(kb_name)
    except KnowledgeBaseError as exc:
        _fail(str(exc))
        return

    colors = {"added": "green", "updated": "cyan", "unchanged": "dim", "failed": "red"}

    def progress(status: str, path: Path, detail: str) -> None:
        if quiet or status == "unchanged":
            return
        color = colors.get(status, "white")
        console.print(
            f"  [{color}]{status:>9}[/] {path}" + (f" [dim]({detail})[/]" if detail else "")
        )

    try:
        report = kb.ingest(paths, recursive=recursive, force=force, progress=progress)
    except FileNotFoundError as exc:
        kb.close()
        _fail(str(exc))
        return
    for source, warns in report.warnings.items():
        for w in warns:
            console.print(f"  [yellow]warning[/] {Path(source).name}: {w}")
    console.print(
        f"[bold]{kb_name}[/]: {len(report.added)} added, {len(report.updated)} updated, "
        f"{len(report.unchanged)} unchanged, {len(report.failed)} failed - "
        f"{report.chunks} chunks in {report.seconds:.2f}s"
    )
    kb.close()
    if report.failed and not report.processed and not report.unchanged:
        raise typer.Exit(1)


@app.command()
def remove(
    source: str = typer.Argument(..., help="Source path or doc id."), kb_name: str = KB_OPTION
) -> None:
    """Remove one document from a knowledge base."""
    try:
        with _manager().get(kb_name) as kb:
            ok = kb.remove(source)
    except KnowledgeBaseError as exc:
        _fail(str(exc))
        return
    if not ok:
        _fail(f"no document matching {source!r}")
    console.print(f"Removed {source}")


# ------------------------------------------------------------------------ query
def _filters(modality: list[str] | None, source: list[str] | None) -> SearchFilters | None:
    f = SearchFilters()
    try:
        if modality:
            f.modalities = [Modality.parse(m) for value in modality for m in value.split(",")]
    except ValueError as exc:
        _fail(str(exc))
    if source:
        f.sources = list(source)
    return None if f.is_empty() else f


@app.command()
def query(
    question: str = typer.Argument(
        ..., help="Question. Inline filters like modality:code work too."
    ),
    kb_name: str = KB_OPTION,
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="none (extractive, default), ollama[:model] or openai[:model]. Env: OMNIRAG_LLM.",
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", min=1, max=50, help="Number of sources."),
    modality: list[str] | None = typer.Option(None, "--modality", "-m", help="Restrict modality."),
    source: list[str] | None = typer.Option(None, "--source", "-s", help="Source glob/substring."),
    mode: str = typer.Option("hybrid", "--mode", help=f"Retrieval mode: {', '.join(MODES)}."),
    neighbors: int = typer.Option(
        1, "--neighbors", min=0, max=3, help="Neighbour chunks for context."
    ),
    hyde: bool = typer.Option(False, "--hyde", help="Use HyDE query expansion (needs an LLM)."),
    as_json: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    show_sources: bool = typer.Option(
        True, "--sources/--no-sources", help="Print the source list."
    ),
) -> None:
    r"""Ask a question and get an answer with \[n] citations."""
    settings = Settings.from_env()
    llm_name = llm or settings.llm
    try:
        with _manager().get(kb_name) as kb:
            answer = kb.ask(
                question,
                llm=llm_name,
                k=top_k,
                filters=_filters(modality, source),
                mode=mode,
                neighbors=neighbors,
                hyde=hyde,
            )
    except (KnowledgeBaseError, LLMError, ValueError) as exc:
        _fail(str(exc))
        return
    if as_json:
        print(json.dumps(answer.to_dict(), indent=2, default=str))
        return
    for warning in answer.warnings:
        err.print(f"[yellow]warning:[/] {warning}")
    console.print(
        Panel(
            Markdown(answer.text),
            title=f"[bold]{question}[/]",
            subtitle=f"{answer.backend} - {answer.timings.get('total_ms', 0):.0f} ms",
            border_style="cyan",
        )
    )
    if show_sources and answer.sources:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("#", justify="right")
        table.add_column("cited")
        table.add_column("modality")
        table.add_column("source")
        table.add_column("score", justify="right")
        for s in answer.sources:
            table.add_row(
                f"[{s.index}]",
                "yes" if s.index in answer.cited else "",
                s.modality,
                s.metadata.get("path", s.label) + (f" ({s.location})" if s.location else ""),
                f"{s.score:.3f}",
            )
        console.print(table)


@app.command()
def search(
    text: str = typer.Argument(..., help="Search text (inline filters supported)."),
    kb_name: str = KB_OPTION,
    top_k: int = typer.Option(10, "--top-k", "-k", min=1, max=100),
    modality: list[str] | None = typer.Option(None, "--modality", "-m"),
    mode: str = typer.Option("hybrid", "--mode", help=f"Retrieval mode: {', '.join(MODES)}."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Retrieval only: show the ranked chunks without generating an answer."""
    try:
        with _manager().get(kb_name) as kb:
            result = kb.search(
                text, k=top_k, filters=_filters(modality, None), mode=mode, neighbors=0
            )
    except (KnowledgeBaseError, ValueError) as exc:
        _fail(str(exc))
        return
    if as_json:
        rows = [
            {
                "chunk_id": r.chunk.chunk_id,
                "source": r.chunk.source,
                "modality": r.chunk.modality.value,
                "score": r.score,
                "retrieval": r.retrieval,
                "content": r.chunk.content,
            }
            for r in result.results
        ]
        print(json.dumps(rows, indent=2, default=str))
        return
    for i, r in enumerate(result.results, start=1):
        ranks = ", ".join(f"{k}#{v}" for k, v in r.retrieval.get("ranks", {}).items())
        console.print(
            f"[bold]{i}.[/] [cyan]{r.chunk.metadata.get('path', r.chunk.source)}[/] "
            f"[dim]({r.chunk.modality.value}, score {r.score:.3f}; {ranks})[/]"
        )
        preview = " ".join(r.chunk.content.split())
        console.print(f"   {preview[:220]}{'...' if len(preview) > 220 else ''}", markup=False)


@app.command()
def stats(kb_name: str = KB_OPTION, as_json: bool = typer.Option(False, "--json")) -> None:
    """Show knowledge base statistics."""
    try:
        with _manager().get(kb_name) as kb:
            s = kb.stats()
            docs = kb.documents()
    except KnowledgeBaseError as exc:
        _fail(str(exc))
        return
    if as_json:
        print(json.dumps(s.to_dict(), indent=2))
        return
    table = Table(title=f"Knowledge base: {s.name}", show_header=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("documents", str(s.documents))
    table.add_row("chunks", str(s.chunks))
    for mod in Modality:
        if s.by_modality.get(mod.value):
            table.add_row(
                f"  {mod.value}",
                f"{s.documents_by_modality.get(mod.value, 0)} docs / {s.by_modality[mod.value]} chunks",
            )
    table.add_row("embedder", f"{s.embedder} (dim {s.dimension or '-'})")
    table.add_row("avg chunk", f"{s.avg_chunk_chars:.0f} chars")
    table.add_row("storage", _human_bytes(s.storage_bytes))
    table.add_row("created", s.created_at or "-")
    table.add_row("updated", s.last_updated or "-")
    table.add_row("path", s.path)
    console.print(table)
    if docs:
        console.print(
            f"[dim]{len(docs)} document(s); first: {', '.join(Path(d.source).name for d in docs[:8])}[/]"
        )


# ----------------------------------------------------------------------- doctor
@app.command()
def doctor(
    network: bool = typer.Option(
        True, "--network/--no-network", help="Probe Ollama / OpenAI-compatible endpoints."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the checks as JSON."),
) -> None:
    """Check Python, the data dir, the embedder, model servers and optional extras."""
    from omnirag.doctor import FAIL, run_checks

    checks = run_checks(Settings.from_env(), home=state.home, network=network)
    failed = [c for c in checks if c.status == FAIL]
    if as_json:
        print(json.dumps([c.to_dict() for c in checks], indent=2))
    else:
        styles = {"ok": "green", "warn": "yellow", "fail": "bold red", "info": "dim"}
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("status")
        table.add_column("check", style="bold")
        table.add_column("detail")
        for c in checks:
            table.add_row(f"[{styles[c.status]}]{c.status:>4}[/]", escape(c.name), escape(c.detail))
        console.print(table)
        console.print(
            f"[bold red]{len(failed)} problem(s) found[/]" if failed else "[green]All good.[/]"
        )
    if failed:
        raise typer.Exit(1)


# ------------------------------------------------------------------------ serve
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8000, "--port", "-p", help="Port."),
    kb_name: str = KB_OPTION,
) -> None:
    """Start the API server and web UI."""
    try:
        import uvicorn

        from omnirag.server.app import create_app
    except ImportError:
        _fail("the web server needs extra packages: pip install 'omnirag[server]'")
        return
    application = create_app(home=state.home, default_kb=kb_name)
    console.print(f"OmniRAG web UI on [bold]http://{host}:{port}[/]  (Ctrl+C to stop)")
    uvicorn.run(application, host=host, port=port, log_level="info")


def main() -> None:
    # Make sure citations, bullets and box drawing survive legacy Windows code pages.
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.encoding and stream.encoding.lower() not in {"utf-8", "utf8"}:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
