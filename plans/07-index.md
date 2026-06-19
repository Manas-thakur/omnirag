# Part 7: `omnirag-index` — Knowledge Base Management

## Purpose

The index package manages the lifecycle of knowledge bases: creating, updating, merging, rebuilding, and monitoring multi-modal indices. It builds on the vector index foundation from AgentCore but adds multi-modal awareness.

## Component Breakdown

### 7.1 Knowledge Base Concept

**File:** `omnirag/index/knowledge_base.py`

```python
@dataclass
class KnowledgeBase:
    """A collection of multi-modal documents with a searchable index."""
    
    name: str
    description: str
    created_at: datetime
    document_count: int
    chunk_count: int
    modalities: list[Modality]
    stats: KBStats

@dataclass
class KBStats:
    total_documents: int
    total_chunks: int
    by_modality: dict[str, int]
    total_tokens: int
    storage_bytes: int
    last_updated: datetime
    index_type: str              # "hnsw", "ivf", "flat"
    index_parameters: dict       # {M, ef_search, nlist, ...}
    average_chunk_size: int
```

### 7.2 Index Manager

**File:** `omnirag/index/manager.py`

```python
class IndexManager:
    """Manage multiple knowledge bases."""
    
    def __init__(self, storage_path: str = "./omnirag_indices/"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def create(
        self,
        name: str,
        description: str = "",
        index_type: str = "hnsw",
        index_params: dict | None = None,
    ) -> KnowledgeBase: ...
    
    def get(self, name: str) -> KnowledgeBase: ...
    
    def delete(self, name: str) -> None: ...
    
    def list(self) -> list[KnowledgeBase]: ...
    
    async def rebuild(self, name: str, new_params: dict | None = None) -> KnowledgeBase:
        """Rebuild index with new parameters."""
        ...
    
    async def merge(self, sources: list[str], target: str) -> KnowledgeBase:
        """Merge multiple knowledge bases into one."""
        ...
    
    def stats(self, name: str) -> KBStats: ...
```

### 7.3 Index Operations

**File:** `omnirag/index/operations.py`

```python
class IndexOperations:
    """Low-level index operations."""
    
    @staticmethod
    def optimize(index: VectorIndex, target_recall: float = 0.95) -> None:
        """Tune index parameters to achieve target recall."""
        ...
    
    @staticmethod
    def prune(index: VectorIndex, min_last_accessed: datetime) -> int:
        """Remove chunks not accessed since given date."""
        ...
    
    @staticmethod
    def shard(index: VectorIndex, n_shards: int) -> list[VectorIndex]:
        """Split index into smaller shards for parallel search."""
        ...

    @staticmethod
    def export(index: VectorIndex, format: str = "fiss") -> bytes:
        """Export index to portable format."""
        ...

    @staticmethod
    def import_index(data: bytes, format: str = "fiss") -> VectorIndex:
        """Import index from portable format."""
        ...
```

### 7.4 Incremental Updates

**File:** `omnirag/index/incremental.py`

```python
class IncrementalUpdater:
    """Efficiently update the index when new documents are added."""
    
    def __init__(self, store: UnifiedStore, index: VectorIndex):
        self.store = store
        self.index = index
    
    async def add_documents(self, documents: list[Document]) -> int:
        """Add new documents to store and index.
        
        Strategy:
        1. Only embed new documents (check content hash)
        2. Add new embeddings to vector index
        3. Update metadata index
        """
        added = 0
        for doc in documents:
            if self._is_new(doc):
                chunks = await self.store.add_document(doc)
                for chunk in chunks:
                    self.index.add_item(chunk.embedding, chunk.chunk_id)
                added += 1
        return added
    
    async def remove_documents(self, doc_ids: list[str]) -> int:
        """Remove documents from store and index."""
        removed = 0
        for doc_id in doc_ids:
            doc = await self.store.get_document(doc_id)
            if doc:
                for chunk_id in doc.chunks or []:
                    self.index.delete([chunk_id])
                await self.store.delete_document(doc_id)
                removed += 1
        return removed
```

---

## File Structure

```
packages/python/index/
├── __init__.py
├── knowledge_base.py         # KnowledgeBase, KBStats
├── manager.py                # IndexManager
├── operations.py             # IndexOperations (optimize, prune, shard, export)
├── incremental.py            # IncrementalUpdater
└── config.py                 # IndexConfig (default index parameters)
```
