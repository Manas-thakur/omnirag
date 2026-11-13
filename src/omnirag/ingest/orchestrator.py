"""Discovers files, routes each one to the right ingestor and collects
cross-file context (such as image alt text found in Markdown documents)."""

from __future__ import annotations

import os
import stat
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


def _within(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == r or path.is_relative_to(r) for r in roots)


def _resolved(paths: Iterable[str | Path] | None) -> list[Path]:
    out = []
    for p in paths or ():
        try:
            out.append(Path(p).expanduser().resolve())
        except OSError:
            continue
    return out


def _is_link(path: Path) -> bool:
    """Symlinks and (on Windows) directory junctions."""
    try:
        return path.is_symlink() or path.is_junction()
    except (AttributeError, OSError):  # is_junction: Python 3.12+
        return path.is_symlink()


def discover(
    paths: Iterable[str | Path],
    recursive: bool = True,
    exclude: Iterable[str | Path] | None = None,
    allow: Iterable[str | Path] | None = None,
    skipped: dict[str, str] | None = None,
) -> list[Path]:
    """Expand files/directories into a sorted, de-duplicated list of supported files.

    * Files under any ``exclude`` directory (OmniRAG's own data directory) are
      never returned, unless they are also under an ``allow`` directory.
    * Folder walks do not follow symlinks or junctions that lead outside the
      folder, and skip special files (sockets, FIFOs, devices).
    * Explicitly named files that cannot be ingested are recorded in
      ``skipped`` (path -> reason) instead of being dropped silently.
    """
    excluded = _resolved(exclude)
    allowed = _resolved(allow)
    skipped = skipped if skipped is not None else {}
    found: dict[str, Path] = {}

    def blocked(path: Path) -> bool:
        return _within(path, excluded) and not _within(path, allowed)

    for raw in paths:
        if not str(raw).strip():
            raise ValueError("empty path: name a file or folder to ingest")
        p = Path(raw).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"path not found: {raw}")
        resolved = p.resolve()
        if p.is_file():
            # Explicitly named files are always ingested (if supported).
            if blocked(resolved):
                skipped[str(resolved)] = "inside the OmniRAG data directory"
            elif detect_modality(p) is None:
                skipped[str(resolved)] = f"unsupported file type: {p.suffix or p.name}"
            else:
                found[str(resolved)] = resolved
            continue
        if not p.is_dir():
            skipped[str(resolved)] = "not a regular file or folder"
            continue
        if blocked(resolved):
            skipped[str(resolved)] = "inside the OmniRAG data directory"
            continue
        for dirpath, dirnames, filenames in os.walk(resolved):
            here = Path(dirpath)
            keep = []
            for d in dirnames:
                sub = here / d
                if d in IGNORED_DIRS or d.startswith(".") or not recursive:
                    continue
                if _is_link(sub):
                    # Never walked: a link inside the folder points at files that
                    # are reached directly anyway, and one leading outside (or
                    # back up, in a loop) must not be followed.
                    if not _within(sub.resolve(), [resolved]):
                        skipped[str(sub)] = "link to a folder outside the ingested folder"
                    continue
                if blocked(sub.resolve()):
                    continue
                keep.append(d)
            dirnames[:] = sorted(keep)
            for name in filenames:
                if name.startswith("."):
                    continue
                f = here / name
                try:
                    real = f.resolve()
                    st = real.stat()
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue  # sockets, FIFOs, devices
                if not _within(real, [resolved]):
                    skipped[str(f)] = "link to a file outside the ingested folder"
                    continue
                if blocked(real) or detect_modality(real) is None or is_sidecar(real):
                    continue
                if st.st_size > MAX_FILE_BYTES:
                    continue
                found[str(real)] = real
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

    def prepare(
        self,
        paths: Iterable[str | Path],
        recursive: bool = True,
        exclude: Iterable[str | Path] | None = None,
        allow: Iterable[str | Path] | None = None,
        skipped: dict[str, str] | None = None,
    ) -> list[Path]:
        paths = list(paths)
        files = discover(paths, recursive=recursive, exclude=exclude, allow=allow, skipped=skipped)
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
