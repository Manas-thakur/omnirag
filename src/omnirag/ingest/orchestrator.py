"""Discovers files, routes each one to the right ingestor and collects
cross-file context (such as image alt text found in Markdown documents)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from omnirag.ingest.audio import TRANSCRIPT_SIDECAR_EXTENSIONS, AudioIngestor
from omnirag.ingest.base import IngestContext, IngestError, Ingestor, ParsedDocument, read_text_file
from omnirag.ingest.code import CodeIngestor
from omnirag.ingest.detector import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, detect_modality
from omnirag.ingest.image import ImageIngestor
from omnirag.ingest.table import TableIngestor
from omnirag.ingest.text import TextIngestor, html_to_text, markdown_image_refs
from omnirag.store.models import Modality

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

MAX_FILE_BYTES = 50 * 1024 * 1024


def default_ingestors() -> dict[Modality, Ingestor]:
    return {
        Modality.TEXT: TextIngestor(),
        Modality.CODE: CodeIngestor(),
        Modality.TABLE: TableIngestor(),
        Modality.IMAGE: ImageIngestor(),
        Modality.AUDIO: AudioIngestor(),
    }


def is_sidecar(path: Path) -> bool:
    """True if ``path`` is a caption/transcript belonging to a media file next to it."""
    ext = path.suffix.lower()
    if ext == ".txt":
        for image_ext in IMAGE_EXTENSIONS:
            # diagram.png.txt
            if path.name.lower().endswith(image_ext + ".txt") and path.with_suffix("").is_file():
                return True
            # diagram.caption.txt / diagram.txt
            stem = path.stem[: -len(".caption")] if path.stem.endswith(".caption") else path.stem
            for variant in (image_ext, image_ext.upper()):
                if path.with_name(stem + variant).is_file():
                    return True
    if ext in TRANSCRIPT_SIDECAR_EXTENSIONS:
        for audio_ext in AUDIO_EXTENSIONS:
            for variant in (audio_ext, audio_ext.upper()):
                if path.with_suffix(variant).is_file():
                    return True
    return False


def discover(paths: Iterable[str | Path], recursive: bool = True) -> list[Path]:
    """Expand files/directories into a sorted, de-duplicated list of supported files."""
    found: dict[str, Path] = {}
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"path not found: {raw}")
        if p.is_file():
            # Explicitly named files are always ingested (if supported).
            if detect_modality(p) is not None:
                found[str(p.resolve())] = p.resolve()
            continue
        iterator = p.rglob("*") if recursive else p.glob("*")
        for f in iterator:
            if not f.is_file():
                continue
            rel_parts = f.relative_to(p).parts
            if any(part in IGNORED_DIRS or part.startswith(".") for part in rel_parts[:-1]):
                continue
            if f.name.startswith("."):
                continue
            if detect_modality(f) is None or is_sidecar(f):
                continue
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found[str(f.resolve())] = f.resolve()
    return sorted(found.values(), key=lambda x: str(x).lower())


def collect_alt_texts(files: Iterable[Path]) -> dict[str, list[str]]:
    """Map resolved image paths to alt texts found in Markdown/HTML files."""
    alt: dict[str, list[str]] = {}
    for f in files:
        ext = f.suffix.lower()
        if ext not in {".md", ".markdown", ".mdx", ".html", ".htm"}:
            continue
        try:
            text = read_text_file(f)
        except OSError:
            continue
        refs = html_to_text(text)[2] if ext in {".html", ".htm"} else markdown_image_refs(text)
        for target, desc in refs:
            if not desc or "://" in target or target.startswith("data:"):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            resolved = (f.parent / target).resolve()
            alt.setdefault(str(resolved), []).append(desc)
    return alt


class IngestionPipeline:
    """Parse files into :class:`ParsedDocument` objects."""

    def __init__(self, ctx: IngestContext | None = None, ingestors: dict | None = None) -> None:
        self.ctx = ctx or IngestContext()
        self.ingestors: dict[Modality, Ingestor] = ingestors or default_ingestors()

    def parse(self, path: Path) -> ParsedDocument:
        modality = detect_modality(path)
        if modality is None:
            raise IngestError(f"unsupported file type: {path.suffix or path.name}")
        ingestor = self.ingestors[modality]
        doc = ingestor.ingest(path, self.ctx)
        doc.chunks = [c for c in doc.chunks if c.content.strip()]
        return doc

    def prepare(self, paths: Iterable[str | Path], recursive: bool = True) -> list[Path]:
        paths = list(paths)
        files = discover(paths, recursive=recursive)
        dirs = [Path(p).resolve() for p in paths if Path(p).is_dir()]
        if len(dirs) == 1 and self.ctx.root is None:
            self.ctx.root = dirs[0]
        elif self.ctx.root is None and files:
            self.ctx.root = Path(_common_parent(files))
        self.ctx.alt_texts.update(collect_alt_texts(files))
        return files


def _common_parent(files: list[Path]) -> str:
    import os

    try:
        common = os.path.commonpath([str(f.parent) for f in files])
    except ValueError:
        return str(files[0].parent)
    return common
