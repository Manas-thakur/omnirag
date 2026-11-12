"""Answer synthesis: context assembly, LLM backends, extractive fallback, citations."""

from omnirag.generate.citation import CitationTracker, Source
from omnirag.generate.context import SYSTEM_PROMPT, ContextAssembler, build_messages, count_tokens
from omnirag.generate.extractive import ExtractiveAnswerer
from omnirag.generate.generator import Answer, AnswerGenerator
from omnirag.generate.llm import LLM, LLMError, OllamaLLM, OpenAICompatibleLLM, create_llm

__all__ = [
    "LLM",
    "SYSTEM_PROMPT",
    "Answer",
    "AnswerGenerator",
    "CitationTracker",
    "ContextAssembler",
    "ExtractiveAnswerer",
    "LLMError",
    "OllamaLLM",
    "OpenAICompatibleLLM",
    "Source",
    "build_messages",
    "count_tokens",
    "create_llm",
]
