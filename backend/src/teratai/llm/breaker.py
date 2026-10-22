"""Process-wide circuit breaker for the model API (SPEC §6 "LLM down / timeout").

One timeout costs `LLM_TIMEOUT_S` x (1 + retries) seconds, and a case makes up to three model calls (extract,
investigator, reply), so a dead API would make every case wait a minute or more. After a timeout, connection
error or 5xx the breaker opens for `LLM_BREAKER_SECONDS`: calls that would reach the network raise
`LLMUnavailable` at once, and every caller already treats that as "degraded" (extract -> regex clues,
investigator -> NEEDS_INFO, reply -> template). Cache hits never touch the breaker, so recorded answers keep
replaying while it is open. After the window the next call goes through and probes the API again.
"""

from __future__ import annotations

import threading
import time

from teratai.llm import settings
from teratai.llm.base import LLMUnavailable

_lock = threading.Lock()
_open_until = 0.0  # time.monotonic() value; 0 = closed
_reason = ""


def _now() -> float:
    return time.monotonic()


def check() -> None:
    """Raise `LLMUnavailable` while the breaker is open."""
    with _lock:
        remaining = _open_until - _now()
        reason = _reason
    if remaining > 0:
        raise LLMUnavailable(f"LLM circuit breaker open for another {remaining:.0f}s after: {reason}")


def trip(reason: str) -> None:
    """Open the breaker for `LLM_BREAKER_SECONDS` (0 disables it)."""
    global _open_until, _reason
    seconds = settings.breaker_seconds()
    if seconds <= 0:
        return
    with _lock:
        _open_until = _now() + seconds
        _reason = reason[:200]


def reset() -> None:
    global _open_until, _reason
    with _lock:
        _open_until, _reason = 0.0, ""
