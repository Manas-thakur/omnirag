# Part 3: `omnirag-store` — Unified Multi-Modal Store

## Purpose

The store package provides a unified interface for persisting and querying multi-modal documents and their embeddings. It combines a vector index (for semantic search) with a document store (for full content retrieval) and a metadata index (for filtered queries).

## Architecture

```
UnifiedStore
├── VectorIndex (from agentcore-index)
│   ├── HNSW / IVF for similarity search
│   └── Pluggable backends: LanceDB, pgvector
│
├── MetadataIndex
│   ├── SQLite for local
│   └── PostgreSQL for cloud
│   └── Filters: modality, date, source, tags
│
├── DocumentStore
│   ├── Stores full document content + chunks
│   └── Backends: filesystem, SQLite, S3
│
└── Query API: search(query, filters) → ScoredChunks
```

## Component Breakdown

### 3.1 Document and Chunk Models

**File:** `omnirag/store/models.py`

```python
@dataclass
class Document:
    doc_id: str                    # Unique ID (hash of content + source)
    content: str | bytes           # Original content
    modality: Modality
    metadata: dict                 # {source, title, author, date, url, ...}
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    chunks: list[str] | None = None  # Child chunk IDs

@dataclass
class Chunk:
    chunk_id: str                  # Unique ID
    doc_id: str                    # Parent document
    content: str                   # Text content (or description for non-text)
    embedding: np.ndarray | None = None
    modality: Modality
    metadata: dict                 # {position, heading, source_ref, ...}
    parent_chunk_id: str | None = None  # For hierarchical chunking

@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    retrieval_info: RetrievalInfo  # How this was retrieved
```

### 3.2 UnifiedStore Interface

**File:** `omnirag/store/unified.py`

```python
class UnifiedStore:
    """Combined vector store + metadata index + document store."""
    
    def __init__(
        self,
        vector_backend: str = "lancedb",   # "lancedb", "chroma", "pgvector"
        metadata_backend: str = "sqlite",   # "sqlite", "postgresql"
        doc_backend: str = "sqlite",        # "sqlite", "filesystem"
        connection_params: dict | None = None,
    ):
        self.vector_index = self._create_vector_index(vector_backend, connection_params)
        self.metadata_index = self._create_metadata_index(metadata_backend, connection_params)
        self.doc_store = self._create_doc_store(doc_backend, connection_params)
    
    async def add_document(self, document: Document, chunks: list[Chunk]) -> None: ...
    async def add_documents(self, documents: list[tuple[Document, list[Chunk]]]) -> None: ...
    
    async def search(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[ScoredChunk]: ...
    
    async def get_document(self, doc_id: str) -> Document | None: ...
    async def get_chunk(self, chunk_id: str) -> Chunk | None: ...
    
    async def delete_document(self, doc_id: str) -> None: ...
    async def delete_chunks(self, chunk_ids: list[str]) -> None: ...
    
    async def stats(self) -> StoreStats: ...

@dataclass
class SearchFilters:
    modalities: list[Modality] | None = None
    date_range: tuple[datetime, datetime] | None = None
    sources: list[str] | None = None
    tags: list[str] | None = None
    metadata_filter: dict | None = None  # Arbitrary key-value pairs

@dataclass
class StoreStats:
    total_documents: int
    total_chunks: int
    by_modality: dict[str, int]
    storage_bytes: int
    vector_index_size_bytes: int
```

### 3.3 Metadata Index

**File:** `omnirag/store/metadata.py`

```python
class MetadataIndex(ABC):
    """Filter chunks by metadata fields."""
    
    @abstractmethod
    async def add_chunk(self, chunk: Chunk) -> None: ...
    
    @abstractmethod
    async def filter(self, filters: SearchFilters) -> list[str]:  # Returns chunk IDs
        ...
    
    @abstractmethod
    async def delete(self, chunk_id: str) -> None: ...

class SQLiteMetadataIndex(MetadataIndex):
    """Local metadata index using SQLite."""
    
    def __init__(self, db_path: str = "./omnirag_meta.db"):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
    
    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT,
                content TEXT,
                modality TEXT,
                source TEXT,
                created_at TIMESTAMP,
                tags TEXT,  -- JSON array
                metadata TEXT  -- JSON object
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_modality ON chunks(modality)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON chunks(created_at)")
```

### 3.4 Document Store

**File:** `omnirag/store/document_store.py`

```python
class DocumentStore(ABC):
    """Store and retrieve full document content."""
    
    @abstractmethod
    async def store(self, document: Document) -> None: ...
    @abstractmethod
    async def retrieve(self, doc_id: str) -> Document | None: ...
    @abstractmethod
    async def delete(self, doc_id: str) -> None: ...

class SQLiteDocumentStore(DocumentStore):
    """Store document content in SQLite (good for text, small docs)."""
    
    def __init__(self, db_path: str = "./omnirag_docs.db"):
        ...
    
    async def store(self, document):
        self.conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
            (document.doc_id, document.content, document.modality.value, json.dumps(document.metadata))
        )

class FileSystemDocumentStore(DocumentStore):
    """Store document content on filesystem (good for large files, images)."""
    
    def __init__(self, base_path: str = "./omnirag_data/"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    async def store(self, document):
        doc_dir = self.base_path / document.doc_id[:2]  # Shard by prefix
        doc_dir.mkdir(exist_ok=True)
        
        path = doc_dir / f"{document.doc_id}.{document.modality.value}"
        if isinstance(document.content, str):
            path.write_text(document.content)
        else:
            path.write_bytes(document.content)
```

---

## File Structure

```
packages/python/store/
├── __init__.py
├── models.py                 # Document, Chunk, ScoredChunk, SearchFilters
├── unified.py                # UnifiedStore
├── metadata.py               # MetadataIndex ABC, SQLiteMetadataIndex, PostgreSQLMetadataIndex
├── document_store.py         # DocumentStore ABC, SQLiteDocumentStore, FileSystemDocumentStore
└── errors.py                 # DocumentNotFoundError, IndexError
```
