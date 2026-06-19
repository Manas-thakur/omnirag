# Part 6: `omnirag-generate` — Multi-Modal Response Synthesis

## Purpose

The generate package is the final step: take the retrieved chunks and synthesize them into a coherent, well-cited response. It handles multi-pass generation (outline → draft → critique → revise → final), citation tracking, multi-modal output (text + images + code), and streaming.

## Component Breakdown

### 6.1 Context Assembly

**File:** `omnirag/generate/context.py`

```python
class ContextAssembler:
    """Pack retrieved chunks into the LLM context window.
    
    Prioritizes high-relevance chunks, stays within token budget,
    and formats sources for citation.
    """
    
    def __init__(self, max_tokens: int = 4096, token_counter: TokenCounter = None):
        self.max_tokens = max_tokens
        self.token_counter = token_counter or TokenCounter()
    
    def assemble(
        self,
        query: str,
        chunks: list[ScoredChunk],
    ) -> tuple[str, CitationTracker]:
        """Assemble context string from chunks within token budget.
        
        Returns: (context_string, citation_tracker)
        """
        tracker = CitationTracker()
        context_parts = []
        tokens_used = 0
        
        for i, scored in enumerate(chunks):
            idx = i + 1
            chunk_text = f"Source [{idx}]:\n{scored.chunk.content}\n"
            chunk_tokens = self.token_counter.count(chunk_text)
            
            if tokens_used + chunk_tokens > self.max_tokens:
                break
            
            tracker.add_source(idx, scored)
            context_parts.append(chunk_text)
            tokens_used += chunk_tokens
        
        context = f"""Answer the following question using the provided sources.
Always cite your sources using [source_number] notation at the end of each sentence.

Question: {query}

Sources:
{''.join(context_parts)}

Answer:"""
        
        return context, tracker

class TokenCounter:
    """Count tokens in text."""
    
    def __init__(self, model: str = "gpt-3.5-turbo"):
        try:
            import tiktoken
            self.encoder = tiktoken.encoding_for_model(model)
        except ImportError:
            self.encoder = None
    
    def count(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        return len(text) // 4  # Rough approximation
```

### 6.2 Citation Tracker

**File:** `omnirag/generate/citation.py`

```python
class CitationTracker:
    """Track which sources support which claims in the generated response."""
    
    def __init__(self):
        self.sources: dict[int, ScoredChunk] = {}
        self.claim_citations: list[dict] = []  # {claim, sources, verified}
    
    def add_source(self, idx: int, chunk: ScoredChunk) -> None:
        self.sources[idx] = chunk
    
    def cite(self, *indices: int) -> str:
        """Generate citation string: [1][2]"""
        return "".join(f"[{i}]" for i in sorted(indices) if i in self.sources)
    
    def format_bibliography(self) -> str:
        """Generate bibliography from tracked sources."""
        lines = ["\n## Sources\n"]
        for idx, chunk in sorted(self.sources.items()):
            source = chunk.chunk.metadata.get("source", "Unknown")
            title = chunk.chunk.metadata.get("title", "")
            date = chunk.chunk.metadata.get("date", "")
            lines.append(f"[{idx}] {title} — {source} ({date})")
        return "\n".join(lines)
    
    def extract_citations_from_response(self, response: str) -> list[str]:
        """Parse [1], [2] citations from generated response."""
        return re.findall(r'\[(\d+)\]', response)
    
    def verify_citations(self, response: str, model_client) -> dict[str, bool]:
        """Verify that each citation actually supports the claim it's attached to."""
        # For each citation, prompt LLM: "Does source [N] support: '{sentence}'?"
        ...
```

### 6.3 Multi-Pass Generation Pipeline

**File:** `omnirag/generate/pipeline.py`

```python
class MultiPassGenerator:
    """Generate high-quality responses through iterative refinement.
    
    Pipeline:
    1. Outline: plan the response structure
    2. Draft: write each section
    3. Critique: review for accuracy and completeness
    4. Revise: improve based on critique
    5. Finalize: format and add citations
    """
    
    def __init__(self, model_client: ModelClient, config: GenerationConfig):
        self.model = model_client
        self.config = config
    
    async def generate(
        self,
        query: str,
        chunks: list[ScoredChunk],
        stream: bool = False,
    ) -> GenerationResult:
        """Generate a response using multi-pass refinement."""
        
        tracker = CitationTracker()
        assembler = ContextAssembler(max_tokens=self.config.max_context_tokens)
        context, tracker = assembler.assemble(query, chunks)
        
        # Step 1: Outline
        outline = await self._generate_outline(query, context)
        
        # Step 2: Draft (section by section)
        draft = await self._generate_draft(query, context, outline)
        
        # Step 3: Critique
        if self.config.review_enabled:
            critique = await self._critique(draft, query, context)
            
            # Step 4: Revise
            if critique.needs_revision:
                draft = await self._revise(draft, critique, context)
        
        # Step 5: Finalize
        final = self._finalize(draft, tracker)
        
        return GenerationResult(
            response=final,
            citation_tracker=tracker,
            outline=outline,
            draft_history=[draft],
            usage=self._total_usage(),
        )
    
    async def _generate_outline(self, query: str, context: str) -> str:
        """Generate a structured outline for the response."""
        prompt = f"""Create a detailed outline for answering this question.
Question: {query}
Sources: {context[:1000]}...
Outline format:
## 1. Section Title
### 1.1 Subsection
- Key points to cover"""
        
        response = await self.model.generate(prompt, max_tokens=512)
        return response.content
    
    async def _generate_draft(self, query: str, context: str, outline: str) -> str:
        """Generate the full draft following the outline."""
        prompt = f"""Write a comprehensive answer following this outline.
Use inline citations [source_number] for every factual claim.

Question: {query}
Outline: {outline}

Sources:
{context}

Write the complete answer now:"""
        
        response = await self.model.generate(prompt, max_tokens=self.config.max_tokens)
        return response.content
    
    async def _critique(self, draft: str, query: str, context: str) -> Critique:
        """Review the draft for issues."""
        prompt = f"""Review this answer for accuracy and completeness:

Question: {query}
Answer: {draft}
Sources: {context[:2000]}

Identify:
1. Factual errors (claims not supported by sources)
2. Missing information
3. Unclear explanations
4. Missing citations
5. Improvements suggested

Format as structured JSON."""
        
        response = await self.model.generate(prompt, max_tokens=1024)
        return Critique.parse(response.content)
    
    async def _revise(self, draft: str, critique: Critique, context: str) -> str:
        """Revise the draft based on critique."""
        prompt = f"""Revise this answer to address the critique:

Original: {draft}
Critique: {critique.to_text()}
Sources: {context[:2000]}

Revised answer:"""
        
        response = await self.model.generate(prompt, max_tokens=self.config.max_tokens)
        return response.content
    
    def _finalize(self, draft: str, tracker: CitationTracker) -> str:
        """Add bibliography and formatting."""
        return draft + "\n" + tracker.format_bibliography()
```

### 6.4 Multi-Modal Response Output

**File:** `omnirag/generate/output.py`

```python
@dataclass
class MultiModalResponse:
    text: str                                  # Main text response
    images: list[ImageRef]                     # Referenced images
    code_blocks: list[CodeBlock]               # Code blocks with language
    tables: list[TableBlock]                   # Table data
    citations: list[CitationRef]               # Source citations
    
@dataclass
class ImageRef:
    path: str                                  # Path or URL
    caption: str                               # Generated caption
    inline_position: int                       # Position in text

@dataclass
class CodeBlock:
    language: str
    code: str
    caption: str | None

class ResponseFormatter:
    """Format the final response, potentially including images and code."""
    
    def format(self, text: str, chunks: list[ScoredChunk]) -> MultiModalResponse:
        """Parse the generated text and extract multi-modal elements."""
        
        images = []
        code_blocks = []
        tables = []
        
        # Check if response references image sources
        for chunk in chunks:
            if chunk.chunk.modality == Modality.IMAGE:
                images.append(ImageRef(
                    path=chunk.chunk.metadata.get("image_path", ""),
                    caption=chunk.chunk.content[:100],
                ))
            
            if chunk.chunk.modality == Modality.CODE:
                code_blocks.append(CodeBlock(
                    language=chunk.chunk.metadata.get("language", ""),
                    code=chunk.chunk.content,
                ))
        
        return MultiModalResponse(
            text=text,
            images=images,
            code_blocks=code_blocks,
            tables=tables,
            citations=[],
        )
```

---

## File Structure

```
packages/python/generate/
├── __init__.py
├── context.py                # ContextAssembler, TokenCounter
├── citation.py               # CitationTracker
├── pipeline.py               # MultiPassGenerator, GenerationConfig, GenerationResult
├── models.py                 # Critique, GenerationResult
├── output.py                 # MultiModalResponse, ResponseFormatter
└── evaluation.py             # Generation quality metrics
```
