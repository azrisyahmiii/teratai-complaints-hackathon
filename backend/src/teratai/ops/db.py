"""Ops SQLite: users, per-case ops state and the append-only event log. One short-lived connection per call."""

import hashlib
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from teratai.ops import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY, name TEXT, role TEXT, languages TEXT, approval_limit_myr TEXT, pw_hash TEXT);
CREATE TABLE IF NOT EXISTS ops_cases(
  complaint_id TEXT PRIMARY KEY, ops_state TEXT NOT NULL, assigned_to TEXT, escalated_by TEXT,
  escalation_reason TEXT, fraud_outcome TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, complaint_id TEXT, actor TEXT, role TEXT, action TEXT,
  field TEXT, from_value TEXT, to_value TEXT, reason TEXT);
"""

# username, name, role, languages, approval limit (None = unlimited)
SEED_USERS: list[tuple[str, str, str, list[str], str | None]] = [
    ("aina", "Aina Rahman", "officer", ["EN", "MS"], "2000.00"),
    ("daniel", "Daniel Tan", "officer", ["EN"], "2000.00"),
    ("siti", "Siti Nurhaliza", "fraud", ["EN", "MS"], "2000.00"),
    ("raj", "Raj Kumar", "fraud", ["EN"], "2000.00"),
    ("manager", "Farah Ismail", "manager", ["EN", "MS"], None),
]
ITERATIONS = 120_000

_ready: set[str] = set()
_lock = threading.Lock()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, _ = stored.partition("$")
    return secrets.compare_digest(hash_password(password, salt), stored)


def _seed(con: sqlite3.Connection) -> None:
    if con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    pw = settings.demo_password()
    for username, name, role, langs, limit in SEED_USERS:
        con.execute(
            "INSERT INTO users(username, name, role, languages, approval_limit_myr, pw_hash) VALUES(?,?,?,?,?,?)",
            (username, name, role, json.dumps(langs), limit, hash_password(pw)),
        )


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
                    _seed(con)
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
