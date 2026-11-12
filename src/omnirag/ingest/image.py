"""Images are made searchable through *text descriptions*.

Description sources, in priority order:

1. A vision-language model caption (optional; any Ollama vision model such as
   ``llava`` when ``OMNIRAG_VLM_MODEL`` is set).
2. A sidecar caption file next to the image: ``diagram.png.txt``,
   ``diagram.caption.txt`` or ``diagram.txt``.
3. Alt text from Markdown/HTML documents that reference the image.
4. Embedded metadata: SVG ``<title>``/``<desc>``/``<text>``, PNG text chunks,
   EXIF (with the optional ``pillow`` extra).
5. The humanised file name (``auth-flow.png`` -> "auth flow").
"""

from __future__ import annotations

import base64
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

import httpx

from omnirag.chunking import RawChunk
from omnirag.ingest.base import (
    IngestContext,
    Ingestor,
    ParsedDocument,
    humanize_filename,
    read_text_file,
)
from omnirag.store.models import Modality

VLM_PROMPT = (
    "Describe this image in detail for a search index. Include any visible text, "
    "the type of image (diagram, chart, screenshot, photo), the main components and "
    "how they relate."
)


def image_sidecars(path: Path) -> list[Path]:
    """Candidate caption files for an image."""
    return [
        path.with_name(path.name + ".txt"),
        path.with_name(path.stem + ".caption.txt"),
        path.with_name(path.stem + ".txt"),
    ]


def svg_text(path: Path) -> dict[str, Any]:
    """Extract title, description and visible text from an SVG."""
    info: dict[str, Any] = {}
    try:
        root = ET.fromstring(read_text_file(path))
    except ET.ParseError:
        return info
    texts: list[str] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        content = " ".join("".join(el.itertext()).split())
        if tag == "title" and content and "title" not in info:
            info["title"] = content
        elif tag == "desc" and content and "description" not in info:
            info["description"] = content
        elif tag == "text" and content:
            texts.append(content)
        label = el.attrib.get("aria-label")
        if label and "title" not in info:
            info["title"] = label
    if texts:
        info["text"] = list(dict.fromkeys(texts))
    w, h = root.attrib.get("width"), root.attrib.get("height")
    if w and h:
        info["dimensions"] = f"{w}x{h}"
    elif root.attrib.get("viewBox"):
        parts = root.attrib["viewBox"].split()
        if len(parts) == 4:
            info["dimensions"] = f"{parts[2]}x{parts[3]}"
    return info


def png_metadata(path: Path) -> dict[str, Any]:
    """Read IHDR dimensions and tEXt/zTXt/iTXt chunks from a PNG (stdlib only)."""
    info: dict[str, Any] = {}
    try:
        data = path.read_bytes()
    except OSError:
        return info
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return info
    pos = 8
    text: dict[str, str] = {}
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        try:
            if ctype == b"IHDR" and len(body) >= 8:
                w, h = struct.unpack(">II", body[:8])
                info["dimensions"] = f"{w}x{h}"
            elif ctype == b"tEXt":
                key, _, value = body.partition(b"\x00")
                text[key.decode("latin-1")] = value.decode("latin-1")
            elif ctype == b"zTXt":
                key, _, rest = body.partition(b"\x00")
                text[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
            elif ctype == b"iTXt":
                key, _, rest = body.partition(b"\x00")
                compressed = rest[0] == 1
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _tkey, _, value = rest.partition(b"\x00")
                if compressed:
                    value = zlib.decompress(value)
                text[key.decode("latin-1")] = value.decode("utf-8", "replace")
            elif ctype == b"IEND":
                break
        except (zlib.error, IndexError, UnicodeDecodeError, struct.error):
            continue
    if text:
        info["text_chunks"] = text
    return info


def pillow_metadata(path: Path) -> dict[str, Any]:
    """EXIF and dimensions via Pillow, if installed."""
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return {}
    info: dict[str, Any] = {}
    try:
        with Image.open(path) as img:
            info["dimensions"] = f"{img.width}x{img.height}"
            exif = img.getexif()
            wanted = {
                "ImageDescription",
                "Artist",
                "DateTime",
                "Make",
                "Model",
                "XPTitle",
                "XPSubject",
                "XPComment",
                "XPKeywords",
            }
            tags = {}
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if name in wanted:
                    if isinstance(value, bytes):
                        value = value.decode("utf-16-le", "ignore").rstrip("\x00")
                    tags[name] = str(value).strip()
            if tags:
                info["exif"] = tags
    except Exception:
        return info
    return info


def vlm_caption(path: Path, model: str, host: str, timeout: float = 120.0) -> str:
    """Caption an image with an Ollama vision model (e.g. ``llava``)."""
    payload = {
        "model": model,
        "prompt": VLM_PROMPT,
        "images": [base64.b64encode(path.read_bytes()).decode("ascii")],
        "stream": False,
    }
    resp = httpx.post(f"{host.rstrip('/')}/api/generate", json=payload, timeout=timeout)
    resp.raise_for_status()
    return str(resp.json().get("response", "")).strip()


class ImageIngestor(Ingestor):
    modality = Modality.IMAGE

    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        rel = ctx.display_path(path)
        warnings: list[str] = []
        parts: list[str] = []
        sources: list[str] = []
        meta: dict[str, Any] = {
            "image_path": str(path.resolve()),
            "format": path.suffix.lstrip(".").lower(),
        }
        title = ""

        settings = ctx.settings
        if settings.vlm_model and path.suffix.lower() != ".svg":
            try:
                caption = vlm_caption(
                    path, settings.vlm_model, settings.ollama_url, settings.request_timeout
                )
                if caption:
                    parts.append(f"Caption: {caption}")
                    sources.append(f"vlm:{settings.vlm_model}")
            except Exception as exc:
                warnings.append(f"VLM captioning failed ({exc}); using metadata fallbacks")

        for sidecar in image_sidecars(path):
            if sidecar.is_file():
                text = read_text_file(sidecar).strip()
                if text:
                    first = text.splitlines()[0].strip().lstrip("# ").strip()
                    title = title or first[:120]
                    parts.append(f"Caption: {text}")
                    sources.append("sidecar")
                break

        alts = ctx.alt_texts.get(str(path.resolve()), [])
        if alts:
            parts.append("Alt text: " + "; ".join(dict.fromkeys(alts)))
            sources.append("alt-text")
            title = title or alts[0]

        ext = path.suffix.lower()
        embedded: dict[str, Any] = {}
        if ext == ".svg":
            embedded = svg_text(path)
        elif ext == ".png":
            embedded = png_metadata(path)
        pil = pillow_metadata(path) if ext != ".svg" else {}
        for key, value in pil.items():
            embedded.setdefault(key, value)

        if embedded.get("title"):
            title = title or embedded["title"]
            parts.append(f"Title: {embedded['title']}")
        if embedded.get("description"):
            parts.append(f"Description: {embedded['description']}")
        if embedded.get("text"):
            parts.append("Text in image: " + "; ".join(embedded["text"]))
        for key, value in (embedded.get("text_chunks") or {}).items():
            parts.append(f"{key}: {value}")
            if key.lower() in {"title", "description"}:
                title = title or value
        for key, value in (embedded.get("exif") or {}).items():
            parts.append(f"{key}: {value}")
        if (
            embedded.get("title")
            or embedded.get("description")
            or embedded.get("text")
            or embedded.get("text_chunks")
            or embedded.get("exif")
        ):
            sources.append("embedded-metadata")
        if embedded.get("dimensions"):
            meta["dimensions"] = embedded["dimensions"]

        name_words = humanize_filename(path)
        title = title or name_words.title()
        header = f"Image: {title} ({rel})"
        if not sources:
            sources.append("filename")
            warnings.append("no caption found; description is based on the file name only")
        body = [header, f"File name: {name_words}"]
        body.extend(parts)
        if meta.get("dimensions"):
            body.append(f"Dimensions: {meta['dimensions']}")
        meta["description_sources"] = sources
        chunk = RawChunk("\n".join(body), {"kind": "image", "description_sources": sources})
        return ParsedDocument(path, Modality.IMAGE, title, [chunk], meta, warnings)
