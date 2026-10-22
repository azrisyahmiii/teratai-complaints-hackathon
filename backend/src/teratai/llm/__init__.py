"""LLM layer (SPEC §12). Usage: `from teratai.llm import get_provider, settings`."""

from teratai.llm.base import (
    CacheMiss,
    ExtractResult,
    GenerateResult,
    LLMError,
    LLMProvider,
    ToolCall,
    ToolLoopResult,
    Usage,
)
from teratai.llm.factory import MissingApiKey, get_provider
from teratai.llm.pricing import PRICE_TABLE, compute_cost

__all__ = [
    "PRICE_TABLE",
    "CacheMiss",
    "ExtractResult",
    "GenerateResult",
    "LLMError",
    "LLMProvider",
    "MissingApiKey",
    "ToolCall",
    "ToolLoopResult",
    "Usage",
    "compute_cost",
    "get_provider",
]
