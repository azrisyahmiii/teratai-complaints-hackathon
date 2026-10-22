"""Thresholds, limits and paths (SPEC §4.4, §4.5). No file I/O here.

Every value can be overridden with an environment variable of the same name, so a demo tweak is one line.
Defaults for the policy parameters equal `data/policy_parameters.csv` (a test asserts this).
"""

import os
from decimal import Decimal
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _dec(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default))


# --- paths ---------------------------------------------------------------------------------------
# this file is backend/src/teratai/config.py, so parents[2] is backend/ and parents[3] the repo root
BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("TERATAI_DATA_DIR", BACKEND_DIR.parent / "data"))
VAR_DIR = Path(os.environ.get("TERATAI_VAR_DIR", BACKEND_DIR / "var"))

# --- policy_parameters.csv -----------------------------------------------------------------------
AUTO_REFUND_LIMIT_MYR = _dec("AUTO_REFUND_LIMIT_MYR", "500.00")  # refunds above this need a human
VULNERABLE_AGE = _int("VULNERABLE_AGE", 65)  # age on the received date: priority up one level
DEBIT_FEE_WAIVER_AGE = _int("DEBIT_FEE_WAIVER_AGE", 60)  # age on the charge date: debit annual fee waived
DUPLICATE_WINDOW_MINUTES = _int("DUPLICATE_WINDOW_MINUTES", 10)
MATCH_WINDOW_DAYS = _int("MATCH_WINDOW_DAYS", 45)

# --- matcher (SPEC §4.4) -------------------------------------------------------------------------
MATCH_WINDOW_SLACK_DAYS = _int("MATCH_WINDOW_SLACK_DAYS", 1)  # extra day on the 45-day window
DATE_SLACK_DAYS = _int("DATE_SLACK_DAYS", 1)  # exact day D is searched over [D - 1, D + 1]
AMOUNT_EXACT_TOL = _dec("AMOUNT_EXACT_TOL", "0.005")  # exact amount: |a - b| <= 0.005
AMOUNT_APPROX_PCT = _dec("AMOUNT_APPROX_PCT", "0.05")  # approximate amount: within max(5%, RM20)
AMOUNT_APPROX_MIN_MYR = _dec("AMOUNT_APPROX_MIN_MYR", "20.00")
UNIQUE_MARGIN = _int("UNIQUE_MARGIN", 2)  # top score must beat the runner-up by this much
DUPLICATE_LATEST_GAP_MINUTES = _int("DUPLICATE_LATEST_GAP_MINUTES", 10)  # 3+ identical: predecessor gap

# Tie-break score weights, one entry per signal (a new signal is a new key, not a code change elsewhere).
SCORE_WEIGHTS: dict[str, int] = {
    "amount_exact": 3,
    "counterparty": 3,
    "date_exact_day": 2,
    "date_in_range": 1,
    "card_last4": 2,
    "fee_type_month": 5,
}

# Channel families by category (SPEC §4.4). `Fee` rows are matched on description; SERVICE_QUALITY has none.
CHANNEL_FAMILIES: dict[str, tuple[str, ...]] = {
    "DUPLICATE_CHARGE": ("Card POS", "Card e-Commerce"),
    "UNAUTHORISED_CARD": ("Card POS", "Card e-Commerce"),
    "FAILED_TRANSFER": ("DuitNow Transfer", "IBG Transfer"),
    "SCAM_TRANSFER": ("DuitNow Transfer", "IBG Transfer"),
    "ATM_NOT_DISPENSED": ("ATM Withdrawal",),
    "FEE_DISPUTE": ("Fee",),
    "SERVICE_QUALITY": (),
}
