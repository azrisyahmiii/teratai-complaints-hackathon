"""Operations state and append-only history; identities belong to the platform database."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from teratai.ops import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_cases(
  complaint_id TEXT PRIMARY KEY, ops_state TEXT NOT NULL, assigned_to TEXT, escalated_by TEXT,
  escalation_reason TEXT, fraud_outcome TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, complaint_id TEXT, actor TEXT, role TEXT, action TEXT,
  field TEXT, from_value TEXT, to_value TEXT, reason TEXT);
"""

_ready: set[str] = set()
_lock = threading.Lock()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _migrate_assignments(con: sqlite3.Connection) -> None:
    # Keep historical audit actors unchanged; only active ownership uses current IDs.
    for old, new in (("aina", "leon"), ("daniel", "vincent"), ("siti", "azri"),
                     ("raj", "nishan"), ("manager", "asyraf")):
        con.execute("UPDATE ops_cases SET assigned_to=? WHERE assigned_to=?", (new, old))
        con.execute("UPDATE ops_cases SET escalated_by=? WHERE escalated_by=?", (new, old))


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
                    _migrate_assignments(con)
                    _ready.add(key)
        yield con
    finally:
        con.close()


def init() -> None:
    with connect():
        pass


def add_event(
    complaint_id: str | None, actor: str, role: str, action: str, field: str | None,
    from_value: str | None, to_value: str | None, reason: str | None = None,
) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO events(ts, complaint_id, actor, role, action, field, from_value, to_value, reason)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (now(), complaint_id, actor, role, action, field, from_value, to_value, reason),
        )
