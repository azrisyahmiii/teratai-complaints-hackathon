"""`python -m teratai.llm.probe`: one real Haiku call that executes a tool.

Prints tool_use, tool_result, final text, tokens and cost. A second run replays from the disk cache
and prints `cache hit`. `DEMO_MODE=cached` runs it offline from the cache.
"""

from __future__ import annotations

import sys
from typing import Any

from teratai.llm import settings
from teratai.llm.base import LLMError
from teratai.llm.factory import MISSING_KEY_MESSAGE, MissingApiKey, get_provider

TOOLS = [
    {
        "name": "get_customer",
        "description": "Look up a bank customer by ID. Returns name and preferred language.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    }
]


def get_customer(args: dict[str, Any]) -> dict[str, Any]:
    # Stub: the real tool registry lives in tools.py.
    return {"customer_id": args.get("customer_id"), "name": "Nur Aisyah", "preferred_language": "MS"}


def main() -> int:
    try:
        provider = get_provider()
    except MissingApiKey:
        print(MISSING_KEY_MESSAGE)
        return 2
    model = settings.extract_model()
    try:
        result = provider.tool_loop(
            tools=TOOLS,
            handlers={"get_customer": get_customer},
            messages=[
                {
                    "role": "user",
                    "content": "Use the tool to look up customer CUS-00566, then tell me their name "
                    "and preferred language in one sentence.",
                }
            ],
            model=model,
            max_calls=3,
            effort="low",
            prompt_version="probe-v1",
        )
    except LLMError as exc:
        print(f"LLM error: {exc}")
        return 1
    for call in result.tool_calls:
        print(f"tool_use: {call.name}({call.input})")
        print(f"tool_result: {call.output}")
    print(f"final text: {result.text}")
    u = result.usage
    print(f"model: {model}  tokens in/out: {u.tokens_in}/{u.tokens_out}  cost_usd: {u.cost_usd:.6f}  calls: {u.calls}")
    print(f"latency_ms: {u.latency_ms} (recorded live: {u.recorded_latency_ms})")
    print("cache hit" if u.cache_hit else "cache miss (live call, now cached)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
