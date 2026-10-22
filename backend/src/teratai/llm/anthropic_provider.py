"""Anthropic SDK provider (`anthropic` 2.x, Messages API). Used on a cache miss only."""

from __future__ import annotations

import time
from typing import Any

import anthropic

from teratai.llm.base import BaseProvider
from teratai.llm.cache import LLMCache


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Response block -> the dict shape the API accepts back as assistant content."""
    t = block.type
    if t == "text":
        return {"type": "text", "text": block.text}
    if t == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if t == "thinking":
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    if t == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    dumped: dict[str, Any] = block.model_dump(mode="json", exclude_none=True)
    return dumped


class AnthropicProvider(BaseProvider):
    def __init__(
        self, cache: LLMCache, api_key: str | None = None, client: anthropic.Anthropic | None = None
    ) -> None:
        super().__init__(cache)
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)

    def _call_api(self, request: dict[str, Any], key: str) -> dict[str, Any]:
        start = time.perf_counter()
        response = self.client.messages.create(**request)
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = response.usage
        return {
            "model": request["model"],
            "stop_reason": response.stop_reason or "end_turn",
            "content": [_block_to_dict(b) for b in response.content],
            "latency_ms": latency_ms,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_input_tokens or 0,
                "cache_write_tokens": usage.cache_creation_input_tokens or 0,
            },
        }
