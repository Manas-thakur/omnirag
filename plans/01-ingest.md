# Part 1: `omnirag-ingest` — Multi-Modal Ingestion

## Purpose

The ingest package handles loading, analyzing, transforming, and chunking documents across multiple modalities. Each modality has specialized processing (captions for images, transcripts for audio, AST for code) but produces a unified output: text chunks with embeddings.

## Architecture

```
Source File
    │
    ▼
Modality Detector ────► Image ──► OCR + Captioning
    │                       └──► Description: "A diagram showing..."
    ├──► Text ──► Clean + Structure
    ├──► Audio ──► Transcribe (Whisper) + Summarize
    ├──► Code ──► Parse AST + Extract docs
    └──► Table ──► Describe schema + Stats
                            │
                            ▼
                    Unified Chunk:
                    {content: str, embedding, 
                     modality, source, metadata}
```

## Component Breakdown

### 1.1 Modality Detector

**File:** `omnirag/ingest/detector.py`

```python
class ModalityDetector:
    """Detect the modality of a file from extension, MIME type, and content inspection."""
    
    MODALITY_MAP = {
        ".txt": Modality.TEXT,
        ".md": Modality.TEXT,
        ".rst": Modality.TEXT,
        ".html": Modality.TEXT,
        ".htm": Modality.TEXT,
        ".pdf": Modality.TEXT,       # Can also contain images
        ".epub": Modality.TEXT,
        
        ".png": Modality.IMAGE,
        ".jpg": Modality.IMAGE,
        ".jpeg": Modality.IMAGE,
        ".webp": Modality.IMAGE,
        ".svg": Modality.IMAGE,
        ".gif": Modality.IMAGE,
        
        ".mp3": Modality.AUDIO,
        ".wav": Modality.AUDIO,
        ".flac": Modality.AUDIO,
        ".ogg": Modality.AUDIO,
        ".m4a": Modality.AUDIO,
        
        ".py": Modality.CODE,
        ".js": Modality.CODE,
        ".ts": Modality.CODE,
        ".jsx": Modality.CODE,
        ".tsx": Modality.CODE,
        ".java": Modality.CODE,
        ".go": Modality.CODE,
        ".rs": Modality.CODE,
        ".c": Modality.CODE,
        ".cpp": Modality.CODE,
        ".rb": Modality.CODE,
        ".php": Modality.CODE,
        
        ".csv": Modality.TABLE,
        ".tsv": Modality.TABLE,
        ".json": Modality.TABLE,
        ".parquet": Modality.TABLE,
        ".xlsx": Modality.TABLE,
    }

class Modality(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    CODE = "code"
    TABLE = "table"
    VIDEO = "video"  # Future
```

### 1.2 Text Ingestion

**File:** `omnirag/ingest/text.py`

```python
class TextIngestor:
    """Load and preprocess text documents."""
    
    def load(self, path: str | Path) -> Document: ...
    def load_batch(self, paths: list[str]) -> list[Document]: ...

class PDFIngestor(TextIngestor):
    """Extract text + layout + embedded images from PDFs."""
    def __init__(self, extract_images: bool = True, image_min_size: tuple[int, int] = (100, 100)):
        # Uses pypdfium2 for fast, layout-aware PDF extraction
        # If extract_images=True, also extract figures/tables as image Documents
        ...
    
    def load(self, path):
        text = extract_text(path)          # Main text content
        images = extract_images(path)      # Embedded images (figures, diagrams)
        return Document(
            content=text,
            modality=Modality.TEXT,
            metadata={"source": path},
            embedded_images=[Document(img, modality=Modality.IMAGE) for img in images],
        )

class WebIngestor(TextIngestor):
    """Fetch and extract content from URLs."""
    def __init__(self):
        self.extractor = trafilatura  # Fast HTML content extraction
```

### 1.3 Image Ingestion

**File:** `omnirag/ingest/image.py`

**Purpose:** Images can't be directly embedded alongside text (different vector spaces). We solve this by generating rich text descriptions of images using a VLM, and embedding those descriptions.

```python
class ImageIngestor:
    """Load images and generate rich descriptions for embedding."""
    
    def __init__(
        self,
        caption_model: str = "llava",       # VLM for captioning
        ocr_model: str = "surya",           # OCR for text extraction
        device: str = "cuda",
    ):
        self.captioner = VLMCaptioner(caption_model, device)
        self.ocr = OCRProcessor(ocr_model, device)
    
    async def process(self, image_path: str) -> list[Chunk]:
        """Process an image into searchable chunks.
        
        Strategy:
        1. Generate a dense caption using VLM (e.g., "A flowchart showing the authentication process...")
        2. Extract any text using OCR
        3. Combine caption + OCR text into a searchable description
        4. Store as text chunk with image reference
        """
        image = self._load_image(image_path)
        
        # Generate caption (VLM)
        caption = await self.captioner.caption(image)
        
        # Extract text (OCR)
        ocr_text = await self.ocr.extract(image)
        
        # Combine
        description = self._combine(caption, ocr_text)
        
        return [Chunk(
            content=description,
            modality=Modality.IMAGE,
            metadata={
                "source": image_path,
                "original_modality": "image",
                "image_path": image_path,
                "caption": caption,
                "ocr_text": ocr_text,
            }
        )]

class VLMCaptioner:
    """Generate detailed captions using a local Vision-Language Model."""
    
    def __init__(self, model_name: str = "llava-hf/llava-1.5-7b-hf", device="cuda"):
        # Load VLM via Hugging Face transformers or Ollama
        ...
    
    async def caption(self, image: Image.Image, prompt: str = None) -> str:
        """Generate a detailed caption.
        
        Default prompt: "Describe this image in detail, including all text, 
        objects, relationships, and important visual elements."
        """
        ...
    
    async def caption_batch(self, images: list[Image.Image]) -> list[str]:
        """Batch caption for efficiency."""
        ...

class OCRProcessor:
    """Extract text from images using OCR."""
    
    def __init__(self, model: str = "surya"):
        # Surya is a modern OCR model that works well for documents
        ...
    
    async def extract(self, image: Image.Image) -> str:
        """Extract text with layout preservation."""
        ...
```

### 1.4 Audio Ingestion

**File:** `omnirag/ingest/audio.py`

```python
class AudioIngestor:
    """Transcribe audio and generate searchable text."""
    
    def __init__(
        self,
        whisper_model: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",  # For faster-whisper
    ):
        # Uses faster-whisper (CTranslate2 backend) for fast transcription on GPU
        self.model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    
    async def process(self, audio_path: str) -> list[Chunk]:
        """Transcribe audio and chunk by topic."""
        
        # Transcribe
        segments, info = self.model.transcribe(audio_path)
        
        # Chunk by sentence/paragraph with timestamps
        chunks = []
        for segment in segments:
            chunks.append(Chunk(
                content=segment.text,
                modality=Modality.AUDIO,
                metadata={
                    "source": audio_path,
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": self._detect_speaker(segment),  # Optional diarization
                }
            ))
        
        # Optional: generate summary
        summary = await self._generate_summary(chunks)
        chunks.append(Chunk(
            content=summary,
            modality=Modality.TEXT,
            metadata={"source": audio_path, "type": "summary"},
        ))
        
        return chunks
```

### 1.5 Code Ingestion

**File:** `omnirag/ingest/code.py`

```python
class CodeIngestor:
    """Parse and document code files for retrieval."""
    
    SUPPORTED_LANGUAGES = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
        ".rb": "ruby",
    }
    
    async def process(self, code_path: str) -> list[Chunk]:
        """Parse code into documented chunks using AST."""
        
        # 1. Read file
        source = Path(code_path).read_text()
        
        # 2. Parse AST
        tree = ast.parse(source)
        
        # 3. Extract functions, classes, modules
        chunks = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunk = self._function_to_chunk(node, source)
                chunks.append(chunk)
            elif isinstance(node, ast.ClassDef):
                chunk = self._class_to_chunk(node, source)
                chunks.append(chunk)
        
        # 4. If no structure found, chunk by lines
        if not chunks:
            chunks = self._line_chunk(source)
        
        return chunks
    
    def _function_to_chunk(self, node, source) -> Chunk:
        """Extract function with docstring and signature."""
        lines = source.split('\n')
        start_line = node.lineno - 1
        end_line = node.end_lineno
        
        code = '\n'.join(lines[start_line:end_line])
        docstring = ast.get_docstring(node) or ""
        
        # NL description for embedding
        description = (
            f"Function: {node.name}\n"
            f"Signature: {node.name}({', '.join(a.arg for a in node.args.args)})\n"
            f"Documentation: {docstring}\n"
            f"Code:\n```python\n{code}\n```"
        )
        
        return Chunk(
            content=description,
            modality=Modality.CODE,
            metadata={
                "source": source,
                "function": node.name,
                "language": "python",
                "line_start": node.lineno,
                "line_end": node.end_lineno,
            }
        )
```

### 1.6 Table Ingestion

**File:** `omnirag/ingest/table.py`

```python
class TableIngestor:
    """Convert structured data into searchable text descriptions."""
    
    async def process(self, table_path: str) -> list[Chunk]:
        """Load table, generate schema + summary + sample descriptions."""
        
        # 1. Load
        if table_path.endswith('.csv'):
            df = pd.read_csv(table_path)
        elif table_path.endswith('.json'):
            df = pd.read_json(table_path)
        # ...
        
        # 2. Schema description
        schema_desc = self._describe_schema(df)
        
        # 3. Summary statistics
        stats_desc = self._describe_stats(df)
        
        # 4. Row-by-row NL descriptions (sampled)
        sample_rows = []
        for i in range(min(5, len(df))):
            row_desc = self._row_to_text(df.iloc[i])
            sample_rows.append(row_desc)
        
        chunks = [
            Chunk(content=schema_desc, modality=Modality.TABLE, metadata={"type": "schema"}),
            Chunk(content=stats_desc, modality=Modality.TABLE, metadata={"type": "statistics"}),
        ]
        for row in sample_rows:
            chunks.append(Chunk(content=row, modality=Modality.TABLE, metadata={"type": "sample_row"}))
        
        return chunks
    
    def _describe_schema(self, df: pd.DataFrame) -> str:
        return (
            f"Table with {len(df)} rows and {len(df.columns)} columns:\n"
            + "\n".join(f"- {col}: {dtype.name}" for col, dtype in df.dtypes.items())
        )
    
    def _row_to_text(self, row: pd.Series) -> str:
        return " | ".join(f"{col}: {val}" for col, val in row.items())
```

### 1.7 Ingestion Orchestration

**File:** `omnirag/ingest/orchestrator.py`

```python
class IngestionOrchestrator:
    """Coordinate multi-modal ingestion for files and directories."""
    
    def __init__(self, config: IngestionConfig):
        self.detector = ModalityDetector()
        self.ingestors = {
            Modality.TEXT: TextIngestor(),
            Modality.IMAGE: ImageIngestor(config.caption_model, config.ocr_model),
            Modality.AUDIO: AudioIngestor(config.whisper_model),
            Modality.CODE: CodeIngestor(),
            Modality.TABLE: TableIngestor(),
        }
    
    async def ingest_file(self, path: str) -> list[Chunk]:
        modality = self.detector.detect(path)
        ingestor = self.ingestors[modality]
        chunks = await ingestor.process(path)
        return chunks
    
    async def ingest_directory(self, path: str, recursive: bool = True) -> list[Chunk]:
        """Recursively ingest all supported files in a directory."""
        all_chunks = []
        for file_path in self._find_supported_files(path, recursive):
            chunks = await self.ingest_file(file_path)
            all_chunks.extend(chunks)
        return all_chunks
```

---

## File Structure

```
packages/python/ingest/
├── __init__.py
├── detector.py               # ModalityDetector, Modality enum
├── ingestors/
│   ├── __init__.py
│   ├── base.py               # BaseIngestor ABC
│   ├── text.py               # TextIngestor, PDFIngestor, WebIngestor
│   ├── image.py              # ImageIngestor, VLMCaptioner, OCRProcessor
│   ├── audio.py              # AudioIngestor (Whisper integration)
│   ├── code.py               # CodeIngestor (AST parsing)
│   └── table.py              # TableIngestor
├── orchestrator.py           # IngestionOrchestrator
└── models.py                 # Document, Chunk (inherits from core)
```
