#!/usr/bin/env bash
# CLI walkthrough of the showcase corpus. Uses an isolated data dir.
#   bash examples/demo.sh            # extractive answers, fully offline
#   LLM=ollama bash examples/demo.sh # answers from a local Ollama model
set -euo pipefail

cd "$(dirname "$0")/.."
export OMNIRAG_HOME="${OMNIRAG_HOME:-examples/.data}"
LLM="${LLM:-none}"
RUN="${RUN:-uv run omnirag}"

$RUN kb create demo --description "OmniRAG multi-modal sample corpus" 2>/dev/null || true
$RUN ingest examples/corpus --kb demo
$RUN stats --kb demo

$RUN query "How does the rate limiter work?" --kb demo --llm "$LLM"
$RUN query "What was decided about the database migration?" --kb demo --llm "$LLM"
$RUN query "Show me the authentication flow diagram" --kb demo --llm "$LLM"
$RUN query "How much did the Redis cache improve p95 latency?" --kb demo --llm "$LLM"
$RUN search "modality:code token expired" --kb demo -k 3
