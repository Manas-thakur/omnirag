# Part 4: `omnirag-query` — Query Understanding & Routing

## Purpose

Before retrieval happens, the system must understand what the user wants. The query package parses user queries, identifies intent and relevant modalities, and expands/rewrites the query for optimal retrieval.

## Component Breakdown

### 4.1 Query Parser

**File:** `omnirag/query/parser.py`

```python
@dataclass
class ParsedQuery:
    original: str
    intent: QueryIntent
    entities: list[str]               # Key entities extracted
    modality_hints: list[Modality]    # Which modalities to search
    sub_queries: list[str]            # Decomposed sub-questions
    complexity: Literal["simple", "medium", "complex"]
    
class QueryIntent(Enum):
    FACTUAL = "factual"                # "What is the capital of France?"
    EXPLANATORY = "explanatory"        # "Explain how transformers work"
    COMPARATIVE = "comparative"        # "Compare GPTQ vs AWQ"
    PROCEDURAL = "procedural"          # "How do I set up authentication?"
    EXPLORATORY = "exploratory"        # "Tell me about X"
    CODE = "code"                      # "Show me the implementation of..."
    SUMMARIZATION = "summarization"    # "Summarize this document"
    MULTI_MODAL = "multi_modal"        # "Show me the diagram and explain it"
```

**Modality Hint Detection:**
```python
class ModalityHintDetector:
    """Detect which modalities the query likely targets."""
    
    MODALITY_KEYWORDS = {
        Modality.IMAGE: ["diagram", "screenshot", "figure", "chart", "graph", "image", 
                        "photo", "picture", "architecture", "flowchart", "screenshot"],
        Modality.AUDIO: ["recording", "audio", "transcript", "meeting", "podcast", 
                        "talk", "speech", "said", "spoken"],
        Modality.CODE: ["code", "function", "implementation", "class", "method",
                       "API", "function", "source code", "script"],
        Modality.TABLE: ["table", "dataset", "CSV", "spreadsheet", "statistics",
                        "data", "column", "row", "schema"],
    }
    
    def detect(self, query: str) -> list[Modality]:
        query_lower = query.lower()
        hints = set()
        for modality, keywords in self.MODALITY_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                hints.add(modality)
        return list(hints) if hints else [Modality.TEXT]  # Default to text
```

### 4.2 Query Rewriter

**File:** `omnirag/query/rewriter.py`

```python
class QueryRewriter:
    """Expand, improve, and decompose queries for better retrieval."""
    
    def __init__(self, model_client: ModelClient | None = None):
        self.model = model_client  # LLM for semantic rewriting (optional)
    
    def expand_synonyms(self, query: str) -> list[str]:
        """Generate synonym-expanded variants of the query.
        
        Example: "How do I set up authentication?"
        → ["How do I configure authentication?",
           "How to implement login system?",
           "Authentication setup guide"]
        """
        if self.model:
            return self._llm_expand(query)
        return [query]
    
    def decompose(self, query: str) -> list[str]:
        """Split complex queries into sub-queries.
        
        Example: "Compare GPTQ, AWQ, and GGUF quantization methods"
        → ["What is GPTQ quantization?",
           "What is AWQ quantization?",
           "What is GGUF quantization?",
           "GPTQ vs AWQ comparison",
           "GGUF vs GPTQ comparison"]
        """
        ...
    
    def hyde(self, query: str) -> str:
        """Hypothetical Document Embedding: generate a hypothetical ideal document.
        
        Instead of searching with the query, search with a generated document
        that would be the ideal answer. This often improves retrieval.
        """
        # Prompt: "Write a short passage that would perfectly answer this query: {query}"
        # Then embed the passage, not the query
        ...
    
    def step_back(self, query: str) -> str:
        """Generate a broader, step-back abstraction of the query.
        
        Example: "How does the authentication middleware work in FastAPI?"
        → "FastAPI middleware architecture and request processing"
        """
        ...
```

### 4.3 Modality Router

**File:** `omnirag/query/router.py`

```python
class ModalityRouter:
    """Route query to appropriate modalities and retrieval strategies."""
    
    def __init__(self, stores: dict[Modality, UnifiedStore]):
        self.stores = stores
    
    async def route(self, query: ParsedQuery) -> RetrievalPlan:
        """Determine which stores to search and with what strategy."""
        
        plan = RetrievalPlan()
        
        for modality in self._relevant_modalities(query):
            store = self.stores.get(modality)
            if not store:
                continue
            
            if modality == Modality.IMAGE:
                # For images, use CLIP text encoder to search image embeddings
                plan.add_source(modality, store, strategy="clip_text_search")
            elif modality == Modality.AUDIO:
                # For audio, search transcript embeddings
                plan.add_source(modality, store, strategy="transcript_search")
            else:
                # For text/code/table, use standard semantic search
                plan.add_source(modality, store, strategy="semantic_search")
        
        return plan

@dataclass
class RetrievalPlan:
    sources: list[RetrievalSource] = field(default_factory=list)
    
    def add_source(self, modality, store, strategy): ...
    def has_modality(self, modality: Modality) -> bool: ...
```

---

## File Structure

```
packages/python/query/
├── __init__.py
├── parser.py                 # QueryParser, ParsedQuery, QueryIntent
├── rewriter.py               # QueryRewriter (synonyms, decomposition, HyDE, step-back)
├── router.py                 # ModalityRouter, RetrievalPlan
└── detection.py              # ModalityHintDetector
```
