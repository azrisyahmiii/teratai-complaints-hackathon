"""Disk cache (SPEC §10 `llm_cache`) in its own sqlite file, so llm/ never depends on db.py.

key = sha256(model, prompt_version, canonical JSON of the request). One connection per call: thread-safe.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def cache_key(model: str, prompt_version: str, request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(f"{model}\x1f{prompt_version}\x1f{canonical}".encode()).hexdigest()


class LLMCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS llm_cache "
                    "(key TEXT PRIMARY KEY, response TEXT NOT NULL, ts TEXT NOT NULL)"
                )
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        loaded: dict[str, Any] = json.loads(row[0])
        return loaded

    def put(self, key: str, response: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO llm_cache (key, response, ts) VALUES (?, ?, ?)",
                    (key, json.dumps(response, ensure_ascii=False), datetime.now(UTC).isoformat()),
                )
        finally:
            conn.close()
