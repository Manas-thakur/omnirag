"""Knowledge base lifecycle: create, ingest incrementally, stats, rebuild, delete."""

from omnirag.index.knowledge_base import (
    IngestReport,
    KBConfig,
    KBPreferences,
    KBStats,
    KnowledgeBase,
    content_hash,
    doc_id_for,
)
from omnirag.index.manager import IndexManager, KnowledgeBaseError

__all__ = [
    "IndexManager",
    "IngestReport",
    "KBConfig",
    "KBPreferences",
    "KBStats",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "content_hash",
    "doc_id_for",
]
