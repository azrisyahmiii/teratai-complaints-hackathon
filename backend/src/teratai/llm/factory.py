"""Provider selection from env: `DEMO_MODE=cached` -> replay; else `LLM_PROVIDER` (anthropic)."""

from __future__ import annotations

from teratai.llm import settings
from teratai.llm.anthropic_provider import AnthropicProvider
from teratai.llm.base import BaseProvider, LLMError
from teratai.llm.cache import LLMCache
from teratai.llm.replay_provider import ReplayProvider

MISSING_KEY_MESSAGE = "ANTHROPIC_API_KEY missing: add it to .env"


class MissingApiKey(LLMError):
    pass


def get_provider() -> BaseProvider:
    cache = LLMCache(settings.cache_path())
    if settings.demo_mode() == "cached":
        return ReplayProvider(cache)
    name = settings.llm_provider()
    if name != "anthropic":
        raise LLMError(f"LLM_PROVIDER={name!r} is not supported (only 'anthropic'; openai is cut)")
    key = settings.api_key()
    if not key:
        raise MissingApiKey(MISSING_KEY_MESSAGE)
    return AnthropicProvider(cache, api_key=key)
