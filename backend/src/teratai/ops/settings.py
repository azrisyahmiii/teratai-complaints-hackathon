"""Ops service settings. Read from the environment at call time, so tests can switch them per test."""

import os
from pathlib import Path

from teratai import config


def db_path() -> Path:
    return Path(os.environ.get("OPS_DB", config.VAR_DIR / "ops.sqlite"))


def on_shift() -> set[str]:
    """OPS_ON_SHIFT="leon,azri,asyraf" limits auto-assignment to those users (the demo cast); empty means everyone."""
    return {u.strip() for u in os.environ.get("OPS_ON_SHIFT", "").split(",") if u.strip()}
