# Part 8: CLI & Web UI

## Purpose

Provide both a command-line interface for power users and a web interface for interactive use. The CLI is great for batch operations and scripting; the web UI is ideal for interactive queries and exploring results.

## Component Breakdown

### 8.1 CLI (TypeScript)

**File:** `omnirag/typescript/cli/`

```bash
omnirage init                              # Initialize a new knowledge base
omnirag ingest ./documents/                # Ingest all supported files
omnirag ingest ./docs/ --recursive         # Recursive directory ingest
omnirag ingest https://example.com         # Ingest a URL

omnirag query "How does X work?"           # Interactive query
omnirag query "Show diagram of Y" --output report.md  # Query → file
omnirag query "Find image of Z" --modality image      # Filter by modality

omnirag serve                              # Start web UI server (default :3000)

omnirag index list                         # List knowledge bases
omnirag index stats mykb                   # Show KB statistics
omnirag index rebuild mykb                 # Rebuild index
omnirag index merge kb1,kb2 --into combined  # Merge KBs

omnirag config set llm.model llama3.1:8b   # Update configuration
omnirag config set embed.model bge-small   # Update embedding model

omnirag stats                              # Overall usage statistics
omnirag docs open                          # Open docs in browser
```

**Implementation:**
```typescript
// packages/typescript/cli/src/commands/query.ts
import { Command } from 'commander';
import { OmniRAGClient } from '@omnirag/client';

export const queryCommand = new Command('query')
  .argument('<query>', 'The query to ask')
  .option('-k, --top-k <number>', 'Number of results', '10')
  .option('-m, --modality <modality>', 'Filter by modality')
  .option('-o, --output <file>', 'Output file path')
  .action(async (query, options) => {
    const client = new OmniRAGClient();
    
    const result = await client.query({
      query,
      topK: parseInt(options.topK),
      modality: options.modality,
      stream: true,
    });
    
    if (options.output) {
      await fs.writeFile(options.output, result.response);
      console.log(`Written to ${options.output}`);
    } else {
      // Stream to terminal
      for await (const chunk of result.stream()) {
        process.stdout.write(chunk);
      }
      console.log('\n');
      console.log(result.citationTracker.formatBibliography());
    }
  });
```

### 8.2 Web UI (React/TypeScript)

**File:** `omnirag/typescript/webui/`

**Pages:**

| Page | Description |
|------|-------------|
| **Chat** | Main chat interface with message history |
| **Knowledge Base** | Browse ingested documents by modality/source |
| **Settings** | Configure models, chunking, retrieval parameters |
| **Stats** | Usage statistics, query history, cost tracking |

**Chat Interface Components:**

```
┌──────────────────────────────────────────┐
│  OmniRAG Knowledge Assistant    [⚙] [📊] │
├──────────────────────────────────────────┤
│                                          │
│  User: How does the authentication       │
│  system work? Show me the diagram.       │
│                                          │
│  Assistant: The authentication system    │
│  uses JWT-based tokens [1]. Here's the   │
│  architecture diagram:                   │
│                                          │
│  ┌──────────────────────────┐            │
│  │   [Architecture Diagram] │            │
│  └──────────────────────────┘            │
│                                          │
│  Sources:                                │
│  [1] Authentication Docs (auth.md)       │
│  [2] System Architecture (diagram.png)   │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ [Type a message...]     [Send] 📎│    │
│  └──────────────────────────────────┘    │
├──────────────────────────────────────────┤
│  Modality Filters: [Text] [Images] [Code]│
│  Model: Llama 3.1 8B        ⚡ Streaming  │
└──────────────────────────────────────────┘
```

**Source Preview Panel:**
When a citation is hovered or clicked, show a side panel with:
- The source chunk content
- Source metadata (file, page, date)
- Relevance score
- Navigation to neighboring chunks

### 8.3 API Server

**File:** `omnirag/python/api/server.py`

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="OmniRAG API", version="0.1.0")

class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    modalities: list[str] | None = None
    stream: bool = False
    knowledge_base: str = "default"

class QueryResponse(BaseModel):
    response: str
    sources: list[SourceInfo]
    tokens_used: int
    latency_ms: float

@app.post("/api/v1/query")
async def query(request: QueryRequest) -> QueryResponse:
    """Query the knowledge base."""
    ...

@app.get("/api/v1/knowledge-bases")
async def list_knowledge_bases() -> list[KBInfo]:
    ...

@app.post("/api/v1/ingest")
async def ingest(path: str, recursive: bool = False) -> IngestResult:
    """Ingest a file or directory."""
    ...
```

---

## File Structure

```
packages/typescript/
├── cli/
│   ├── package.json
│   ├── src/
│   │   ├── index.ts            # Entry point
│   │   ├── commands/
│   │   │   ├── init.ts
│   │   │   ├── ingest.ts
│   │   │   ├── query.ts
│   │   │   ├── serve.ts
│   │   │   ├── index.ts        # Index management commands
│   │   │   └── config.ts
│   │   └── client.ts           # API client
│   └── README.md
│
├── webui/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Chat.tsx
│   │   │   ├── KnowledgeBase.tsx
│   │   │   ├── Settings.tsx
│   │   │   └── Stats.tsx
│   │   ├── components/
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── SourcePreview.tsx
│   │   │   ├── ModalityFilter.tsx
│   │   │   ├── ImageDisplay.tsx
│   │   │   └── CodeBlock.tsx
│   │   └── styles/
│   │       └── global.css
│   └── README.md
│
└── client/                     # Shared API client
    ├── package.json
    └── src/
        └── index.ts
```
