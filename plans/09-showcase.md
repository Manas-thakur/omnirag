# Part 9: Showcase App — Multi-Modal Knowledge Base

## Purpose

The showcase app demonstrates OmniRAG's capabilities by ingesting a realistic multi-modal corpus and allowing interactive querying across all modalities.

## What It Does

1. **Ingests** a multi-modal corpus containing:
   - Technical documentation (Markdown, HTML, PDF)
   - Architecture diagrams (PNG, SVG with captions)
   - Code repositories (Python, TypeScript, Java)
   - Meeting recordings (MP3 → Whisper transcripts)
   - Dataset descriptions (CSV/Parquet schemas)

2. **Queries** across modalities:
   - "How does the authentication system work?" → text docs + code + diagram
   - "Show me the architecture diagram" → returns the image
   - "What was decided in the architecture review meeting?" → audio transcript
   - "Compare the API latency before and after optimization" → table + code
   - "Find the implementation of the rate limiter" → code chunks

## Demo Dataset: "OpenAI Cookbook Clone"

We'll create a synthetic but realistic multi-modal corpus based on open-source documentation:

| Modality | Content | Source |
|----------|---------|--------|
| Text | FastAPI documentation (markdown) | FastAPI official docs |
| Text | SQLAlchemy tutorial | SQLAlchemy docs |
| Images | Architecture diagrams (DALL-E generated or real) | Various open-source projects |
| Code | FastAPI example app | GitHub |
| Audio | Conference talk transcripts | PyCon YouTube (transcribed) |
| Tables | Performance benchmarks (CSV) | Synthetic |

## Ingestion Pipeline

```bash
# Create and populate the knowledge base
omnirag init my-knowledge-base

# Ingest documentation
omnirag ingest ./docs/fastapi/ --recursive
omnirag ingest ./docs/sqlalchemy/ --recursive

# Ingest code
omnirag ingest ./src/app/ --recursive --modality code

# Ingest diagrams
omnirag ingest ./assets/diagrams/ --recursive

# Ingest transcripts
omnirag ingest ./transcripts/
# Audio auto-detected, Whisper transcription runs automatically

# Ingest data
omnirag ingest ./data/benchmarks.csv

# Check stats
omnirag index stats my-knowledge-base
# Documents: 245
# Chunks: 3,847
# By modality: text=2,100, code=1,200, image=200, audio=300, table=47
```

## Example Queries

### Query 1: Cross-Modal (Text + Image)
```
> How does the authentication middleware work? Show me the diagram.

The authentication system uses JWT-based token validation via middleware [1].
The middleware checks each request for a valid `Authorization: Bearer <token>` header [2].

Here's the architecture diagram:

[Auth Flow Diagram — ./assets/diagrams/auth-flow.png]
Caption: JWT Authentication flow showing token issuance, validation, and refresh

[1] FastAPI Security Documentation — ./docs/fastapi/security.md
[2] Auth Implementation — ./src/app/middleware/auth.py
```

### Query 2: Code-Focused
```
> Find the rate limiter implementation and explain how it works.

The rate limiter uses a token bucket algorithm implemented in `src/app/middleware/rate_limiter.py` [1]:

```python
class TokenBucketRateLimiter:
    def __init__(self, rate: float, burst: int):
        self.rate = rate  # Tokens per second
        self.burst = burst  # Max tokens
        self.tokens = burst
        self.last_refill = time.time()
    
    async def check(self, client_id: str) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True  # Request allowed
        return False  # Rate limited
```

The limiter refills tokens at `rate` per second up to a maximum of `burst` [1]. This allows short bursts of traffic while maintaining a sustainable average rate.

[1] Rate Limiter Implementation — ./src/app/middleware/rate_limiter.py
```

### Query 3: Audio Transcript
```
> What was the team's decision about the database migration?

Based on the architecture review meeting on 2026-05-15 [1]:

The team decided to use a two-phase migration approach:
1. Phase 1 (week 1-2): Add new tables alongside existing ones
2. Phase 2 (week 3-4): Migrate data and drop old tables

Key decisions:
- Use SQLAlchemy 2.0's async session for the new schema
- Keep a compatibility layer for 30 days after migration
- Rollback plan: switch back to old schema within 2 hours

This was discussed in the Architecture Review Meeting (transcript/meeting_2026-05-15.mp3) [1],
specifically at timestamps 12:30-18:45.

[1] Architecture Review Meeting — ./transcripts/meeting_2026-05-15.mp3
```

## Demo Script (Interview-Ready)

```
1. "Let me show you OmniRAG, my multi-modal knowledge assistant."
   → Run: omnirag serve
   → Open browser to localhost:3000

2. "I've ingested ~250 documents: documentation, code, diagrams, and meeting transcripts."
   → Run: omnirag index stats my-knowledge-base

3. "Let's ask a cross-modal question:"
   → Query: "How does authentication work? Show the diagram."
   → Result includes text + image

4. "Now a code question:"
   → Query: "Show me the rate limiter implementation"
   → Result shows code with explanation

5. "Now an audio question:"
   → Query: "What was decided about the database migration?"
   → Result references meeting transcript with timestamps

6. "The system uses multi-pass generation: outline → draft → critique → revise."
   → Show the trace in the dashboard

7. "All built from scratch — no LangChain, no LlamaIndex."
   → Open GitHub to show the code
```

---

## File Structure

```
apps/knowledgebase/
├── __init__.py
├── setup.py                   # Script to create and populate the demo KB
├── seed_data/                 # Demo data (not committed — generated on setup)
│   ├── docs/
│   ├── src/
│   ├── assets/diagrams/
│   ├── transcripts/
│   └── data/
├── queries.md                 # Example queries for demo
└── demo_script.md             # Step-by-step demo script
```
