"""LLM-layer settings, read from env at call time (so tests and demos can override with one line).

Loads `.env` from the repo root and from `backend/` (python-dotenv, never overrides real env vars).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent

_loaded = False


def load_env() -> None:
    global _loaded
    if not _loaded:
        load_dotenv(REPO_ROOT / ".env")
        load_dotenv(BACKEND_DIR / ".env")
        _loaded = True


def _get(name: str, default: str) -> str:
    load_env()
    return os.environ.get(name) or default


def llm_provider() -> str:
    """`anthropic` (default). `openai` is cut from scope."""
    return _get("LLM_PROVIDER", "anthropic").lower()


def demo_mode() -> str:
    """`live` (default) or `cached` (replay provider: only reads the disk cache)."""
    return _get("DEMO_MODE", "live").lower()


def extract_model() -> str:
    return _get("EXTRACT_MODEL", "claude-haiku-5-5")


def reply_model() -> str:
    return _get("REPLY_MODEL", "claude-sonnet-5-5")


def reply_effort() -> str:
    """Thinking effort for replies. Sonnet 5.5 defaults to `high`, too slow/costly for a 120-word reply."""
    return _get("REPLY_EFFORT", "low")


def cache_path() -> Path:
    return Path(_get("LLM_CACHE_PATH", str(BACKEND_DIR / "var" / "llm_cache.sqlite")))


def api_key() -> str | None:
    load_env()
    return os.environ.get("ANTHROPIC_API_KEY") or None
