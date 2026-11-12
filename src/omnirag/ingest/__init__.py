"""Multi-modal ingestion: detect modality, parse, describe and chunk files."""

from omnirag.ingest.audio import AudioIngestor, parse_subtitles
from omnirag.ingest.base import IngestContext, IngestError, Ingestor, ParsedDocument
from omnirag.ingest.code import CodeIngestor
from omnirag.ingest.detector import detect_language, detect_modality, is_supported
from omnirag.ingest.image import ImageIngestor
from omnirag.ingest.orchestrator import IngestionPipeline, collect_alt_texts, discover, is_sidecar
from omnirag.ingest.table import TableIngestor
from omnirag.ingest.text import TextIngestor, html_to_text

__all__ = [
    "AudioIngestor",
    "CodeIngestor",
    "ImageIngestor",
    "IngestContext",
    "IngestError",
    "IngestionPipeline",
    "Ingestor",
    "ParsedDocument",
    "TableIngestor",
    "TextIngestor",
    "collect_alt_texts",
    "detect_language",
    "detect_modality",
    "discover",
    "html_to_text",
    "is_sidecar",
    "is_supported",
    "parse_subtitles",
]
