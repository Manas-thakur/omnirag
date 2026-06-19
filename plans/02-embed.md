# Part 2: `omnirag-embed` — Multi-Modal Embedding

## Purpose

The embed package provides a unified interface for generating embeddings across modalities. The key challenge is that images, audio, and text have different native embedding spaces. We solve this by: (1) using text descriptions as a bridge for non-text content, (2) providing a cross-modal embedding layer that maps everything to a shared space, and (3) supporting quantization for memory efficiency.

## Architecture

```
Embedding Layer
├── TextEmbedder
│   ├── BGE / E5 / GTE (Hugging Face)
│   └── Sentence Transformers
│
├── ImageEmbedder
│   ├── CLIP / SigLIP visual encoder
│   └── For image search (image→image)
│
├── CrossModalEmbedder
│   ├── Uses text descriptions for non-text content
│   └── Everything → shared text embedding space
│
├── EmbeddingCache
│   ├── LRU cache in memory
│   └── Persistent cache in SQLite
│
└── Quantization
    ├── Int8 scalar quantization
    └── Binary quantization
```

## Component Breakdown

### 2.1 Embedder Interface

**File:** `omnirag/embed/base.py`

```python
class Embedder(ABC):
    """Abstract base for all embedders."""
    
    dimension: int
    model_name: str
    
    @abstractmethod
    def embed(self, text: str) -> np.ndarray: ...
    
    @abstractmethod
    def embed_batch(self, texts: list[str]) -> np.ndarray: ...
    
    @abstractmethod
    def normalize(self, vector: np.ndarray) -> np.ndarray: ...
```

### 2.2 TextEmbedder

**File:** `omnirag/embed/text.py`

```python
class TextEmbedder(Embedder):
    """Generate embeddings for text using Hugging Face models."""
    
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        device: str = "cuda",
        batch_size: int = 32,
        normalize: bool = True,
        max_length: int = 512,
    ):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(device)
        self.device = device
        self.batch_size = batch_size
        self.dimension = self.model.config.hidden_size
    
    def embed(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]
    
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            inputs = self.tokenizer(
                batch, padding=True, truncation=True,
                max_length=self.max_length, return_tensors="pt"
            ).to(self.device)
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                # Mean pooling
                embeddings = self._mean_pooling(outputs, inputs["attention_mask"])
                
                if self.normalize:
                    embeddings = F.normalize(embeddings, p=2, dim=1)
                
                all_embeddings.append(embeddings.cpu().numpy())
        
        return np.vstack(all_embeddings)
    
    def _mean_pooling(self, outputs, attention_mask):
        token_embeddings = outputs[0]  # Last hidden state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
```

**Model Recommendations:**

| Model | Dimensions | Performance | Speed | Use Case |
|-------|-----------|-------------|-------|----------|
| `BAAI/bge-small-en-v1.5` | 384 | Good | Fastest | General purpose, default |
| `BAAI/bge-base-en-v1.5` | 768 | Better | Fast | Higher accuracy |
| `BAAI/bge-large-en-v1.5` | 1024 | Best | Slower | Maximum accuracy |
| `intfloat/e5-base-v2` | 768 | Excellent | Fast | Text retrieval |
| `thenlper/gte-base` | 768 | Excellent | Fast | General purpose |

### 2.3 ImageEmbedder (CLIP)

**File:** `omnirag/embed/image.py`

```python
class ImageEmbedder(Embedder):
    """Generate image embeddings using CLIP/SigLIP visual encoder.
    
    Used for image-to-image search and cross-modal retrieval.
    """
    
    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        device: str = "cuda",
    ):
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model = CLIPModel.from_pretrained(model_name).to(device)
        self.dimension = self.model.config.vision_config.hidden_size
    
    def embed_image(self, image: Image.Image) -> np.ndarray:
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            embedding = self.model.get_image_features(**inputs)
            embedding = embedding / embedding.norm(p=2, dim=-1, keepdim=True)
        return embedding.cpu().numpy()[0]
    
    def embed_text(self, text: str) -> np.ndarray:
        """Also embed text in the CLIP space for text→image search."""
        inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            embedding = self.model.get_text_features(**inputs)
            embedding = embedding / embedding.norm(p=2, dim=-1, keepdim=True)
        return embedding.cpu().numpy()[0]
```

### 2.4 CrossModalEmbedder

**File:** `omnirag/embed/cross_modal.py`

**Purpose:** The bridge that maps all modalities to a shared space. For images, we use the generated caption (from VLM). For audio, we use the transcript. For tables, we use the schema description. Everything becomes text, and all text is embedded with the same model.

```python
class CrossModalEmbedder(Embedder):
    """Map any content to a shared embedding space via text descriptions.
    
    Strategy:
    - Text: embed directly
    - Image: use VLM-generated caption as text → embed that
    - Audio: use Whisper transcript as text → embed that
    - Code: use AST-extracted documentation as text → embed that
    - Table: use schema + summary description as text → embed that
    """
    
    def __init__(self, text_embedder: TextEmbedder):
        self.text_embedder = text_embedder
        self.dimension = text_embedder.dimension
    
    def embed_chunk(self, chunk: Chunk) -> np.ndarray:
        """Embed any chunk by extracting its text content."""
        return self.text_embedder.embed(chunk.content)
    
    def embed_chunks(self, chunks: list[Chunk]) -> np.ndarray:
        return self.text_embedder.embed_batch([c.content for c in chunks])
    
    def embed_query(self, query: str) -> np.ndarray:
        """Embed a user query. Apply query-side prefix if the model uses it.
        
        BGE models use: 'Represent this sentence for searching relevant passages: {query}'
        E5 models use: 'query: {query}'
        """
        return self.text_embedder.embed(self._format_query(query))
```

### 2.5 Embedding Cache

**File:** `omnirag/embed/cache.py`

```python
class EmbeddingCache:
    """LRU cache for embeddings with disk persistence."""
    
    def __init__(self, capacity: int = 10000, persistent_path: str | None = None):
        self.cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.capacity = capacity
        self.persistent_path = persistent_path
        if persistent_path:
            self._load()
    
    def get(self, key: str) -> np.ndarray | None:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None
    
    def set(self, key: str, embedding: np.ndarray) -> None:
        self.cache[key] = embedding
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
    
    def _load(self):
        """Load cache from SQLite."""
        ...
```

---

## File Structure

```
packages/python/embed/
├── __init__.py
├── base.py                   # Embedder ABC
├── text.py                   # TextEmbedder
├── image.py                  # ImageEmbedder (CLIP)
├── cross_modal.py            # CrossModalEmbedder
├── cache.py                  # EmbeddingCache
├── quantization.py           # Embedding quantizer (int8, binary)
└── comparison.py             # Similarity computation (cosine, dot, L2)
```
