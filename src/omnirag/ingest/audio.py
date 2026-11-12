"""Audio is made searchable through transcripts.

* ``.vtt`` / ``.srt`` files are parsed directly (with timestamps and speakers).
* For audio files (``.mp3``, ``.wav``, ...) a sidecar transcript with the same
  stem (``meeting.vtt``, ``meeting.srt``, ``meeting.txt``) is used if present.
* Otherwise, if the optional ``faster-whisper`` package is installed, the audio
  is transcribed locally.
* As a last resort a metadata-only chunk is stored so the file is still listed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from omnirag.chunking import RawChunk, split_text
from omnirag.ingest.base import (
    IngestContext,
    Ingestor,
    ParsedDocument,
    humanize_filename,
    read_text_file,
)
from omnirag.ingest.detector import TRANSCRIPT_EXTENSIONS
from omnirag.store.models import Modality

TRANSCRIPT_SIDECAR_EXTENSIONS = (".vtt", ".srt", ".txt")

_TS_RE = re.compile(
    r"(?P<start>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<end>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_VOICE_RE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>")
_TAG_RE = re.compile(r"</?[^>]+>")
_SPEAKER_PREFIX_RE = re.compile(r"^([A-Z][\w .'-]{0,40}):\s+(.*)$")


@dataclass
class Cue:
    start: float | None
    end: float | None
    text: str
    speaker: str | None = None


def parse_timestamp(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    seconds = float(parts[-1])
    if len(parts) >= 2:
        seconds += int(parts[-2]) * 60
    if len(parts) == 3:
        seconds += int(parts[0]) * 3600
    return seconds


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_subtitles(text: str) -> list[Cue]:
    """Parse WebVTT or SRT into cues. Speaker names from ``<v Name>`` tags or
    ``Name: text`` prefixes are preserved."""
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        ts_idx = next((i for i, ln in enumerate(lines) if _TS_RE.search(ln)), None)
        if ts_idx is None:
            continue
        m = _TS_RE.search(lines[ts_idx])
        assert m is not None
        body_lines = lines[ts_idx + 1 :]
        if not body_lines:
            continue
        raw = " ".join(body_lines)
        speaker = None
        vm = _VOICE_RE.search(raw)
        if vm:
            speaker = vm.group(1).strip()
        clean = " ".join(_TAG_RE.sub("", raw).split())
        sm = _SPEAKER_PREFIX_RE.match(clean)
        if not speaker and sm:
            speaker, clean = sm.group(1).strip(), sm.group(2).strip()
        cues.append(
            Cue(parse_timestamp(m.group("start")), parse_timestamp(m.group("end")), clean, speaker)
        )
    return cues


def group_cues(cues: list[Cue], max_chars: int) -> list[list[Cue]]:
    groups: list[list[Cue]] = []
    current: list[Cue] = []
    size = 0
    for cue in cues:
        if current and size + len(cue.text) > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(cue)
        size += len(cue.text) + (len(cue.speaker) + 2 if cue.speaker else 0)
    if current:
        groups.append(current)
    return groups


def transcript_chunks(cues: list[Cue], title: str, max_chars: int) -> list[RawChunk]:
    chunks = []
    for group in group_cues(cues, max_chars):
        start, end = group[0].start, group[-1].end
        lines: list[str] = []
        last_speaker: str | None = None
        for cue in group:
            if cue.speaker and lines and cue.speaker == last_speaker:
                lines[-1] += " " + cue.text
            else:
                stamp = f"[{format_timestamp(cue.start)}] " if cue.start is not None else ""
                lines.append(
                    f"{stamp}{cue.speaker}: {cue.text}" if cue.speaker else stamp + cue.text
                )
            last_speaker = cue.speaker
        speakers = list(dict.fromkeys(c.speaker for c in group if c.speaker))
        header = f"Transcript of {title} [{format_timestamp(start)} - {format_timestamp(end)}]"
        chunks.append(
            RawChunk(
                header + "\n" + "\n".join(lines),
                {
                    "kind": "transcript",
                    "start": start,
                    "end": end,
                    "timestamp": f"{format_timestamp(start)}-{format_timestamp(end)}",
                    "speakers": speakers,
                },
            )
        )
    return chunks


def find_transcript_sidecar(path: Path) -> Path | None:
    for ext in TRANSCRIPT_SIDECAR_EXTENSIONS:
        candidate = path.with_suffix(ext)
        if candidate != path and candidate.is_file():
            return candidate
    return None


def whisper_transcribe(path: Path, model_name: str) -> list[Cue]:
    from faster_whisper import WhisperModel  # optional dependency

    model = WhisperModel(model_name, device="auto", compute_type="default")
    segments, _info = model.transcribe(str(path))
    return [Cue(seg.start, seg.end, seg.text.strip()) for seg in segments if seg.text.strip()]


class AudioIngestor(Ingestor):
    modality = Modality.AUDIO

    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        title = humanize_filename(path).title()
        meta: dict = {"format": path.suffix.lstrip(".").lower()}
        warnings: list[str] = []
        ext = path.suffix.lower()

        transcript_path: Path | None = path if ext in TRANSCRIPT_EXTENSIONS else None
        if transcript_path is None:
            meta["audio_path"] = str(path.resolve())
            transcript_path = find_transcript_sidecar(path)

        cues: list[Cue] = []
        if transcript_path is not None:
            meta["transcript_source"] = transcript_path.name
            text = read_text_file(transcript_path)
            if text.lstrip().startswith("WEBVTT"):
                first = text.lstrip().splitlines()[0]
                extra = first[len("WEBVTT") :].strip(" -")
                if extra:
                    title = extra
            if transcript_path.suffix.lower() in TRANSCRIPT_EXTENSIONS:
                cues = parse_subtitles(text)
            else:
                chunks = [
                    RawChunk(f"Transcript of {title}\n{piece}", {"kind": "transcript"})
                    for piece in split_text(text, ctx.chunk_size, ctx.chunk_overlap)
                ]
                return ParsedDocument(path, Modality.AUDIO, title, chunks, meta, warnings)
        elif ext not in TRANSCRIPT_EXTENSIONS:
            model_name = ctx.settings.whisper_model or "base"
            try:
                cues = whisper_transcribe(path, model_name)
                meta["transcript_source"] = f"faster-whisper:{model_name}"
            except ImportError:
                warnings.append(
                    "no transcript sidecar and faster-whisper is not installed "
                    "(pip install 'omnirag[audio]'); stored metadata only"
                )
            except Exception as exc:
                warnings.append(f"transcription failed: {exc}")

        if cues:
            chunks = transcript_chunks(cues, title, min(ctx.chunk_size, 800))
            meta["duration"] = cues[-1].end
            meta["speakers"] = list(dict.fromkeys(c.speaker for c in cues if c.speaker))
        else:
            size = path.stat().st_size if path.exists() else 0
            chunks = [
                RawChunk(
                    f"Audio recording: {title} ({ctx.display_path(path)}), {size} bytes. "
                    "No transcript available.",
                    {"kind": "audio-metadata"},
                )
            ]
        return ParsedDocument(path, Modality.AUDIO, title, chunks, meta, warnings)
