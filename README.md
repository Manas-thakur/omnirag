# OmniRAG — Multi-Modal RAG-Powered Knowledge Assistant

## Philosophy

OmniRAG extends traditional text-only RAG to handle multiple modalities: text, images, audio, code, and structured data. The core insight is that **all modalities can be mapped into a shared embedding space** using text descriptions as a bridge. An image is captioned, a table is described, code is documented — and all become retrievable via a single semantic search interface.

Built from scratch: no LangChain, no LlamaIndex. Every component — ingestion, chunking, embedding, retrieval, fusion, re-ranking, generation — is custom.

## Why Multi-Modal Matters

Traditional RAG systems handle text only. But real-world knowledge comes in many forms:
- **Technical documentation** has diagrams and architecture charts (images)
- **Code repositories** have function definitions and docstrings (code)
- **Meeting recordings** have spoken insights (audio)
- **Datasets** have schemas and statistical summaries (tables)

A knowledge assistant that can't handle these is incomplete. OmniRAG bridges the gap.

## Architecture

```
Multi-Modal Sources
  ├── Text (PDF, HTML, MD)
  ├── Images (PNG, JPG, SVG)
  ├── Audio (MP3, WAV, transcript)
  ├── Code (Python, JS, TS, etc.)
  └── Tables (CSV, JSON, Parquet)
         │
         ▼
┌─────────────────────────────┐
│      Ingestion Pipeline     │
│  Load → Analyze → Transform │
│  → Chunk → Describe → Embed │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│     Unified Vector Store    │
│  Text + Image Descriptions  │
│  + Transcripts + Code Doc   │
│  + Table Summaries          │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│      Retrieval Layer        │
│  Hybrid Search + Fusion     │
│  + Reranking + Filtering    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│     Multi-Modal Synthesis   │
│  Context Assembly → Plan    │
│  → Draft → Cite → Final     │
└─────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Core** | Python 3.11+ (uv) |
| **Local VLM** | LLaVA / Phi-3-vision / NanoLLaVA on RTX 4060 |
| **Local LLM** | Ollama — Llama 3.1 8B / Qwen 2.5 7B |
| **Speech to Text** | Faster-Whisper (local, on GPU) |
| **OCR** | Surya (local, on GPU) |
| **Image Embedding** | CLIP / SigLIP via Hugging Face |
| **Text Embedding** | BGE / E5 / GTE via Hugging Face |
| **Vector Store** | LanceDB (local) + pgvector/Neon (cloud) |
| **CLI / Web UI** | TypeScript, React, Node 20+ |
| **CI/CD** | GitHub Actions |

## Monorepo Structure

```
omnirag/
├── packages/
│   ├── python/
│   │   ├── ingest/         # Multi-modal ingest: text, image, audio, code, table
│   │   ├── embed/          # Embedding abstraction: text, image, cross-modal
│   │   ├── store/          # Unified vector + structured store
│   │   ├── retrieve/       # Hybrid retrieval + fusion + reranking
│   │   ├── generate/       # Multi-modal response synthesis
│   │   ├── query/          # Query understanding, routing, expansion
│   │   └── index/          # Index management, quantization, persistence
│   └── typescript/
│       ├── cli/            # omnirag CLI
│       └── webui/          # Chat interface with source preview
├── apps/
│   └── knowledgebase/      # Showcase: ingest a multi-modal corpus, query it
├── docs/                   # Astro + MDX blog
└── .github/workflows/      # CI: lint, test, eval
```

## Blog Content Roadmap

| Phase | Posts |
|-------|-------|
| Foundations | "Multi-Modal RAG: Why Text-Only Isn't Enough", "Building a Multi-Modal Ingestion Pipeline" |
| Embedding | "Cross-Modal Embeddings: Mapping Images, Text, and Audio to a Shared Space", "Captioning Images for RAG: VLM vs Dedicated Models" |
| Retrieval | "Fusion Strategies for Multi-Modal Retrieval", "Cross-Modal Re-ranking: Improving Relevance Across Modalities" |
| Generation | "Synthesizing Multi-Modal Responses: Text + Images + Code in One Answer", "Citation Tracking in Multi-Modal RAG" |
| Showcase | "Building a Multi-Modal Knowledge Base: From Ingestion to Query" |
