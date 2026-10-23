"""PRICE_TABLE: US$ per million tokens, Decimal only.

Source: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-10-22).
Haiku 5.5 has a second rate card for prompts over 100,000 tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal  # 5-minute cache write (the default TTL)


def _p(i: str, o: str, r: str, w: str) -> ModelPrice:
    return ModelPrice(Decimal(i), Decimal(o), Decimal(r), Decimal(w))


PRICE_TABLE: dict[str, ModelPrice] = {
    "claude-haiku-5-5": _p("0.10", "0.50", "0.01", "0.125"),
    "claude-sonnet-5-5": _p("2", "10", "0.20", "2.50"),
}

# Haiku 5.5, prompts over LONG_PROMPT_TOKENS.
LONG_PROMPT_TOKENS = 100_000
LONG_PRICE_TABLE: dict[str, ModelPrice] = {
    "claude-haiku-5-5": _p("0.50", "2.50", "0.05", "0.625"),
}


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """`input_tokens` is the uncached input only (as the API reports it). Unknown model -> Decimal(0)."""
    price = PRICE_TABLE.get(model)
    if price is None:
        return Decimal(0)
    prompt_tokens = input_tokens + cache_read_tokens + cache_write_tokens
    if model in LONG_PRICE_TABLE and prompt_tokens > LONG_PROMPT_TOKENS:
        price = LONG_PRICE_TABLE[model]
    total = (
        price.input * input_tokens
        + price.output * output_tokens
        + price.cache_read * cache_read_tokens
        + price.cache_write * cache_write_tokens
    )
    return total / MTOK
