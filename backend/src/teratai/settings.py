"""Platform settings. Read from the environment at call time, so tests can switch them per test."""

import os
from datetime import datetime
from pathlib import Path

from teratai import config


def db_path() -> Path:
    return Path(os.environ.get("TERATAI_DB", config.VAR_DIR / "teratai.sqlite"))


def workers() -> int:
    return int(os.environ.get("WORKERS", "20"))


def sim_now() -> datetime:
    """The simulated clock for SLA figures: live-round complaints are received on 30 Sep 2026 (SPEC 4.1)."""
    return datetime.strptime(os.environ.get("SIM_NOW", "2026-09-30 12:00"), "%Y-%m-%d %H:%M")


def actions_two_tier() -> bool:
    # TODO(ops platform): when True, over-limit approvals escalate to a manager instead of sending (SPEC 7.2).
    return os.environ.get("ACTIONS_TWO_TIER", "0") == "1"


ACTIONS_TWO_TIER = actions_two_tier()
