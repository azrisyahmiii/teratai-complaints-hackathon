"""Ops service settings. Read from the environment at call time, so tests can switch them per test."""

import os
from pathlib import Path

from dotenv import dotenv_values

from teratai import config

DEV_SECRET = "teratai-ops-dev-secret"
COOKIE = "teratai_ops"
SESSION_SECONDS = 8 * 3600


def core_url() -> str:
    return os.environ.get("CORE_URL", "http://localhost:8000").rstrip("/")


def db_path() -> Path:
    return Path(os.environ.get("OPS_DB", config.VAR_DIR / "ops.sqlite"))


def on_shift() -> set[str]:
    """OPS_ON_SHIFT="aina,siti,manager" limits auto-assignment to those users (the demo cast); empty means everyone."""
    return {u.strip() for u in os.environ.get("OPS_ON_SHIFT", "").split(",") if u.strip()}


def secret() -> str:
    return os.environ.get("OPS_SECRET", DEV_SECRET)


def demo_password() -> str:
    """OPS_DEMO_PASSWORD from the environment, else the repo-root .env (the core never loads it), else the demo default."""
    if "OPS_DEMO_PASSWORD" in os.environ:
        return os.environ["OPS_DEMO_PASSWORD"]
    return dotenv_values(config.BACKEND_DIR.parent / ".env").get("OPS_DEMO_PASSWORD") or "teratai-demo"
