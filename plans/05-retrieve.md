# Part 5: `omnirag-retrieve` — Multi-Modal Retrieval & Fusion

## Purpose

The retrieve package handles the actual retrieval: searching multiple modality-specific stores in parallel, fusing results into a unified ranking, and applying re-rankers for precision.

## Component Breakdown

### 5.1 Retrieval Interface

**File:** `omnirag/retrieve/base.py`

```python
class Retriever(ABC):
    """Base class for all retrievers."""
    
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        query_embedding: np.ndarray,
        k: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[ScoredChunk]: ...
```

### 5.2 Retrieval Strategies

**File:** `omnirag/retrieve/strategies.py`

**VectorRetriever:**
```python
class VectorRetriever(Retriever):
    """Standard semantic search using embedding similarity."""
    
    def __init__(self, store: UnifiedStore, embedder: CrossModalEmbedder):
        self.store = store
        self.embedder = embedder
    
    async def retrieve(self, query, query_embedding, k=10, filters=None):
        return await self.store.search(
            query_embedding=query_embedding,
            k=k,
            filters=filters,
        )
```

**BM25Retriever:**
```python
class BM25Retriever(Retriever):
    """Sparse keyword retrieval (complement to dense vector search).
    
    Implementation from scratch using TF-IDF scoring.
    """
    
    def __init__(self, store: UnifiedStore):
        self.store = store
        self.bm25: dict[str, float] = {}  # term → IDF
    
    async def build_index(self):
        """Build BM25 index from stored document content."""
        # Collect all document texts
        # Tokenize → compute IDF for each term
        # Store: term → set of chunk_ids containing it
        ...
    
    async def retrieve(self, query, query_embedding=None, k=10, filters=None):
        # Tokenize query
        # Score each document by BM25: sum of IDF of matching terms
        # Return top-k
        ...
```

**HybridRetriever:**
```python
class HybridRetriever(Retriever):
    """Combine dense + sparse retrieval with reciprocal rank fusion."""
    
    def __init__(
        self,
        vector_retriever: VectorRetriever,
        bm25_retriever: BM25Retriever,
        fusion_method: str = "rrf",      # "rrf", "weighted", "score_norm"
        vector_weight: float = 0.7,
        rrf_k: int = 60,                 # RRF constant
    ):
        self.vector = vector_retriever
        self.bm25 = bm25_retriever
        self.fusion_method = fusion_method
    
    async def retrieve(self, query, query_embedding, k=10, filters=None):
        # Run both retrievers in parallel
        vector_results, bm25_results = await asyncio.gather(
            self.vector.retrieve(query, query_embedding, k=k * 2, filters=filters),
            self.bm25.retrieve(query, k=k * 2, filters=filters),
        )
        
        # Fusion
        return self._fuse(vector_results, bm25_results, k)
    
    def _fuse_rrf(self, vector, bm25, k):
        """Reciprocal Rank Fusion: score = Σ 1/(k + rank_i)"""
        scores: dict[str, float] = {}
        for rank, result in enumerate(vector):
            scores[result.chunk.chunk_id] = scores.get(result.chunk.chunk_id, 0) + 1 / (self.rrf_k + rank + 1)
        for rank, result in enumerate(bm25):
            scores[result.chunk.chunk_id] = scores.get(result.chunk.chunk_id, 0) + 1 / (self.rrf_k + rank + 1)
        
        # Sort by score, return top-k
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:k]
        # Map back to ScoredChunks
        ...
```

### 5.3 Cross-Modal Fusion

**File:** `omnirag/retrieve/fusion.py`

```python
class CrossModalFusion:
    """Fuse results from multiple modality-specific retrievers."""
    
    def __init__(self, retrievers: dict[Modality, Retriever]):
        self.retrievers = retrievers
    
    async def retrieve(
        self,
        query: str,
        query_embedding: np.ndarray,
        modalities: list[Modality],
        k: int = 10,
    ) -> list[ScoredChunk]:
        """Search each modality in parallel, fuse results."""
        
        tasks = {
            mod: retriever.retrieve(query, query_embedding, k=k // len(modalities))
            for mod, retriever in self.retrievers.items()
            if mod in modalities
        }
        
        results = await asyncio.gather(*tasks.values())
        
        return self._fuse_with_modality_boost(results, list(tasks.keys()), k)
    
    def _fuse_with_modality_boost(
        self,
        results: list[list[ScoredChunk]],
        modalities: list[Modality],
        k: int,
    ) -> list[ScoredChunk]:
        """Fuse with modality boost factors.
        
        Some queries naturally prefer certain modalities:
        - Code queries → boost code results
        - Image queries → boost image results
        """
        all_results = []
        for result_list in results:
            all_results.extend(result_list)
        
        # Sort by score with modality weighting
        all_results.sort(key=lambda x: x.score * self._modality_weight(x.chunk.modality), reverse=True)
        
        return all_results[:k]
```

### 5.4 Re-ranking

**File:** `omnirag/retrieve/reranker.py`

```python
class CrossEncoderReranker:
    """Re-rank candidates using a cross-encoder model (more accurate but slower)."""
    
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", device="cuda"):
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.device = device
    
    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        k: int = 5,
    ) -> list[ScoredChunk]:
        """Score each (query, chunk) pair with cross-encoder, return top-k."""
        
        pairs = [(query, c.chunk.content) for c in candidates]
        
        inputs = self.tokenizer(
            pairs, padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            scores = self.model(**inputs).logits.squeeze(-1).cpu().numpy()
        
        # Update scores
        for i, candidate in enumerate(candidates):
            candidate.score = float(scores[i])
        
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:k]

class MMRReranker:
    """Maximal Marginal Relevance: balance relevance and diversity.
    
    Prevents redundant chunks from dominating the result set.
    """
    
    def __init__(self, lambda_param: float = 0.7, embedding_model: Embedder = None):
        self.lambda_param = lambda_param
        self.embedder = embedding_model
    
    def rerank(self, query_embedding: np.ndarray, candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]:
        selected = []
        remaining = list(candidates)
        
        for _ in range(min(k, len(candidates))):
            best = None
            best_score = -float('inf')
            
            for candidate in remaining:
                relevance = candidate.score
                
                if selected:
                    # Compute max similarity to already selected
                    candidate_emb = candidate.chunk.embedding
                    max_sim = max(
                        cosine_similarity([candidate_emb], [s.chunk.embedding])[0][0]
                        for s in selected
                    )
                else:
                    max_sim = 0
                
                mmr = self.lambda_param * relevance - (1 - self.lambda_param) * max_sim
                
                if mmr > best_score:
                    best_score = mmr
                    best = candidate
            
            if best:
                selected.append(best)
                remaining.remove(best)
        
        return selected
```

### 5.5 Chunk Augmentation

**File:** `omnirag/retrieve/augmentation.py`

```python
class ChunkAugmenter:
    """Augment retrieved chunks with parent context for richer generation."""
    
    def __init__(self, store: UnifiedStore):
        self.store = store
    
    async def augment(self, chunks: list[ScoredChunk], strategy: str = "parent") -> list[ScoredChunk]:
        """Add context to retrieved chunks.
        
        Strategies:
        - "parent": retrieve the parent chunk that contains this one
        - "siblings": retrieve neighboring chunks
        - "window": retrieve chunks before and after
        """
        if strategy == "parent":
            for chunk in chunks:
                if chunk.chunk.parent_chunk_id:
                    parent = await self.store.get_chunk(chunk.chunk.parent_chunk_id)
                    if parent:
                        chunk.chunk.content = f"{parent.content}\n\n{chunk.chunk.content}"
        return chunks
```

---

## File Structure

```
packages/python/retrieve/
├── __init__.py
├── base.py                   # Retriever ABC
├── strategies/
│   ├── __init__.py
│   ├── vector.py             # VectorRetriever
│   ├── bm25.py               # BM25Retriever (from scratch)
│   └── hybrid.py             # HybridRetriever
├── fusion.py                 # CrossModalFusion
├── reranker.py               # CrossEncoderReranker, MMRReranker
├── augmentation.py           # ChunkAugmenter
└── evaluation.py             # Retrieval metrics (recall@k, mrr, ndcg)
```
