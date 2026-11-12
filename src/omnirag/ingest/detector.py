"""Modality detection from file extension, with a light content sniff fallback."""

from __future__ import annotations

from pathlib import Path

from omnirag.store.models import Modality

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".mdx", ".rst", ".html", ".htm", ".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
TRANSCRIPT_EXTENSIONS = {".vtt", ".srt"}
_SNIFFABLE_SUFFIXES = {".text", ".log", ".cfg", ".ini", ".toml", ".yaml", ".yml"}
TABLE_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".ndjson"}

CODE_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".lua": "lua",
    ".r": "r",
}


def detect_modality(path: str | Path) -> Modality | None:
    """Return the modality for ``path`` or ``None`` if it is unsupported."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return Modality.TEXT
    if ext in IMAGE_EXTENSIONS:
        return Modality.IMAGE
    if ext in AUDIO_EXTENSIONS or ext in TRANSCRIPT_EXTENSIONS:
        return Modality.AUDIO
    if ext in TABLE_EXTENSIONS:
        return Modality.TABLE
    if ext in CODE_LANGUAGES:
        return Modality.CODE
    return _sniff(p)


def detect_language(path: str | Path) -> str | None:
    p = Path(path)
    lang = CODE_LANGUAGES.get(p.suffix.lower())
    if lang:
        return lang
    head = _head(p)
    if head and head.startswith("#!"):
        first = head.splitlines()[0]
        for name in ("python", "node", "bash", "sh"):
            if name in first:
                return {"node": "javascript", "bash": "shell", "sh": "shell"}.get(name, name)
    return None


def _head(path: Path, size: int = 2048) -> str | None:
    try:
        with path.open("rb") as fh:
            data = fh.read(size)
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _sniff(path: Path) -> Modality | None:
    """Files without a known extension: treat readable UTF-8 text as text/code."""
    if path.suffix and path.suffix.lower() not in _SNIFFABLE_SUFFIXES:
        return None
    head = _head(path)
    if head is None or not head.strip():
        return None
    if head.startswith("#!"):
        return Modality.CODE
    return Modality.TEXT


def is_supported(path: str | Path) -> bool:
    return detect_modality(path) is not None
