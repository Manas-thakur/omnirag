"""OmniRAG: a multi-modal RAG knowledge assistant built from scratch.

Quick start::

    from omnirag import IndexManager

    kb = IndexManager().get_or_create("notes")
    kb.ingest(["./docs", "./src"])
    answer = kb.ask("How does the rate limiter work?")
    print(answer.text)
    for source in answer.cited_sources:
        print(source.index, source.label)
"""

from omnirag.config import Settings
from omnirag.generate import Answer, Source
from omnirag.index import IndexManager, IngestReport, KnowledgeBase, KnowledgeBaseError
from omnirag.store import Chunk, Document, Modality, ScoredChunk, SearchFilters

__version__ = "0.2.0"

__all__ = [
    "Answer",
    "Chunk",
    "Document",
    "IndexManager",
    "IngestReport",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "Modality",
    "ScoredChunk",
    "SearchFilters",
    "Settings",
    "Source",
    "__version__",
]
