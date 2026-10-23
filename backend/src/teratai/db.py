"""SQLite storage (SPEC 10, trimmed to what the organisers' API needs). One short-lived connection per call."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from teratai import settings

LIVE = "live"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(
  complaint_id TEXT NOT NULL, run_id TEXT NOT NULL, row JSON, status TEXT NOT NULL, error TEXT,
  agent_decision JSON, flags JSON, case_state TEXT, sent INTEGER, human_action JSON,
  created_at TEXT, updated_at TEXT, submitted_by TEXT, PRIMARY KEY(run_id, complaint_id));
CREATE TABLE IF NOT EXISTS case_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, complaint_id TEXT, ts TEXT, actor TEXT, action TEXT,
  stage TEXT, payload JSON, model TEXT, tokens_in INTEGER, tokens_out INTEGER, cost_usd TEXT,
  latency_ms INTEGER, ok INTEGER);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, complaint_id TEXT, ts TEXT, language TEXT, text TEXT,
  authorised_by TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, pw_hash TEXT, role TEXT, languages TEXT,
  approval_limit_myr TEXT, status TEXT, shift_start TEXT, shift_end TEXT, max_capacity INTEGER,
  last_assigned_at TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, run_id TEXT, complaint_id TEXT, message TEXT,
  seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(
  username TEXT NOT NULL, source TEXT NOT NULL, at INTEGER NOT NULL);
"""

_ready: set[str] = set()
_lock = threading.Lock()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = settings.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=30000")
        key = str(path)
        if key not in _ready:
            with _lock:
                if key not in _ready:
                    con.execute("PRAGMA journal_mode=WAL")
                    con.executescript(SCHEMA)
                    columns = {r["name"] for r in con.execute("PRAGMA table_info(cases)")}
                    if "submitted_by" not in columns:
                        con.execute("ALTER TABLE cases ADD COLUMN submitted_by TEXT")
                    _ready.add(key)
        yield con
    finally:
        con.close()


def init() -> None:
    with connect():
        pass


def get_case(run_id: str, complaint_id: str) -> sqlite3.Row | None:
    with connect() as con:
        row: sqlite3.Row | None = con.execute(
            "SELECT * FROM cases WHERE run_id=? AND complaint_id=?", (run_id, complaint_id)
        ).fetchone()
        return row


def insert_processing(run_id: str, complaint_id: str, row_json: str, submitted_by: str | None = None) -> bool:
    """True if inserted, False if the case already existed (atomic)."""
    t = now()
    with connect() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO cases(complaint_id, run_id, row, status, created_at, updated_at, submitted_by) "
            "VALUES(?,?,?,?,?,?,?)",
            (complaint_id, run_id, row_json, "processing", t, t, submitted_by),
        )
        return cur.rowcount == 1


def set_error(run_id: str, complaint_id: str, error: str) -> None:
    with connect() as con:
        con.execute(
            "UPDATE cases SET status='error', error=?, updated_at=? WHERE run_id=? AND complaint_id=?",
            (error, now(), run_id, complaint_id),
        )


def add_event(
    run_id: str,
    complaint_id: str,
    actor: str,
    action: str | None,
    stage: str | None,
    payload: dict[str, Any],
    *,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: str = "0",
    latency_ms: int = 0,
    ok: bool = True,
) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO case_events(run_id, complaint_id, ts, actor, action, stage, payload, model, tokens_in,"
            " tokens_out, cost_usd, latency_ms, ok) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, complaint_id, now(), actor, action, stage, json.dumps(payload, default=str), model,
             tokens_in, tokens_out, cost_usd, latency_ms, int(ok)),
        )
