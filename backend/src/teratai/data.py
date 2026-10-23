"""Loads the bank CSVs once and indexes them (SPEC §14 `data.py`). This is the only module that reads data/.

Money is `Decimal` parsed from the CSV string, never via float. Times are naive MYT `datetime`.
Empty CSV cells become "" (strings) so callers compare with `== ""`, not `is None`.
Lookups by id raise `KeyError`; use `has_customer` / `has_txn` to test existence (e.g. intake validation).
"""

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path

from teratai import config
from teratai.models import ComplaintRow


@dataclass(frozen=True)
class Customer:
    customer_id: str
    full_name: str
    date_of_birth: date
    state: str
    city: str
    segment: str
    preferred_language: str  # "EN" | "MS"
    email: str
    customer_since: date


@dataclass(frozen=True)
class Account:
    account_id: str
    customer_id: str
    product: str
    open_date: date
    status: str
    card_last4: str  # "" for current accounts


@dataclass(frozen=True)
class Txn:
    txn_id: str
    txn_time: datetime
    account_id: str
    customer_id: str
    direction: str  # "DR" | "CR"
    amount: Decimal
    channel: str
    merchant: str  # merchant_or_counterparty
    counterparty_account: str
    counterparty_bank: str
    merchant_country: str
    card_last4: str
    auth_method: str
    status: str  # "Completed" | "Failed"
    description: str


@dataclass(frozen=True)
class AtmJournal:
    txn_id: str
    atm_id: str
    atm_location: str
    requested: Decimal
    dispensed: Decimal
    journal_status: str  # OK | PARTIAL_DISPENSE | DISPENSE_FAULT

    @property
    def shortfall(self) -> Decimal:
        return self.requested - self.dispensed


@dataclass(frozen=True)
class FeeRow:
    fee_code: str
    fee_name: str  # matches the start of a Fee txn description
    product: str  # may list several products ("Basic Savings; Savings Plus (debit ...)")
    amount: Decimal
    waiver_rule: str


@dataclass(frozen=True)
class Label:
    complaint_id: str
    category: str
    matched_txn_id: str  # "" for SERVICE_QUALITY
    outcome: str
    refund_amount: Decimal
    priority: str
    reply_language: str
    route: str


@dataclass(frozen=True)
class SlaRow:
    priority: str
    ack_hours: int
    resolve_business_days: int


@dataclass(frozen=True)
class PolicyRow:
    category: str
    what_it_covers: str
    how_to_find: str
    decision_rule: str  # the rule text shown in the "why" panel
    base_priority: str


_REVERSAL_RE = re.compile(r"Reversal of (TXN-\d{7})")


def _rows(name: str) -> Iterator[dict[str, str]]:
    path: Path = config.DATA_DIR / name
    with path.open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)  # accepts "YYYY-MM-DD HH:MM" and "... HH:MM:SS"


# --- customers, accounts ---------------------------------------------------------------------------


@cache
def _customers() -> dict[str, Customer]:
    return {
        r["customer_id"]: Customer(
            r["customer_id"],
            r["full_name"],
            date.fromisoformat(r["date_of_birth"]),
            r["state"],
            r["city"],
            r["segment"],
            r["preferred_language"],
            r["email"],
            date.fromisoformat(r["customer_since"]),
        )
        for r in _rows("customers.csv")
    }


@cache
def _accounts() -> tuple[dict[str, Account], dict[str, tuple[Account, ...]]]:
    by_id: dict[str, Account] = {}
    by_customer: dict[str, list[Account]] = {}
    for r in _rows("accounts.csv"):
        a = Account(
            r["account_id"],
            r["customer_id"],
            r["product"],
            date.fromisoformat(r["open_date"]),
            r["status"],
            r["card_last4"],
        )
        by_id[a.account_id] = a
        by_customer.setdefault(a.customer_id, []).append(a)
    return by_id, {k: tuple(v) for k, v in by_customer.items()}


def has_customer(customer_id: str) -> bool:
    return customer_id in _customers()


def customer(customer_id: str) -> Customer:
    return _customers()[customer_id]


def customers() -> tuple[Customer, ...]:
    return tuple(_customers().values())


def account(account_id: str) -> Account:
    return _accounts()[0][account_id]


def accounts_for(customer_id: str) -> tuple[Account, ...]:
    return _accounts()[1].get(customer_id, ())


# --- transactions ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TxnIndex:
    by_id: dict[str, Txn]
    by_customer: dict[str, tuple[Txn, ...]]  # sorted by (txn_time, txn_id)
    reversal_by_original: dict[str, Txn]  # original txn_id -> the Reversal CR row that references it


@cache
def _txn_index() -> _TxnIndex:
    by_id: dict[str, Txn] = {}
    per_customer: dict[str, list[Txn]] = {}
    reversals: dict[str, Txn] = {}
    for r in _rows("transactions.csv"):
        t = Txn(
            r["txn_id"],
            _dt(r["txn_time"]),
            r["account_id"],
            r["customer_id"],
            r["direction"],
            Decimal(r["amount_myr"]),
            r["channel"],
            r["merchant_or_counterparty"],
            r["counterparty_account"],
            r["counterparty_bank"],
            r["merchant_country"],
            r["card_last4"],
            r["auth_method"],
            r["status"],
            r["description"],
        )
        by_id[t.txn_id] = t
        per_customer.setdefault(t.customer_id, []).append(t)
        if t.channel == "Reversal":
            m = _REVERSAL_RE.fullmatch(t.description)
            if m:
                reversals[m.group(1)] = t
    by_customer = {k: tuple(sorted(v, key=lambda t: (t.txn_time, t.txn_id))) for k, v in per_customer.items()}
    return _TxnIndex(by_id, by_customer, reversals)


def has_txn(txn_id: str) -> bool:
    return txn_id in _txn_index().by_id


def txn(txn_id: str) -> Txn:
    return _txn_index().by_id[txn_id]


def txns_for(customer_id: str) -> tuple[Txn, ...]:
    """All of a customer's transactions (debits and credits), oldest first."""
    return _txn_index().by_customer.get(customer_id, ())


def reversal_of(txn_id: str) -> Txn | None:
    """The Reversal credit row whose description names `txn_id`, if any."""
    return _txn_index().reversal_by_original.get(txn_id)


def reversal_target(t: Txn) -> str | None:
    """For a Reversal row, the id of the original txn it reverses; None for any other row."""
    if t.channel != "Reversal":
        return None
    m = _REVERSAL_RE.fullmatch(t.description)
    return m.group(1) if m else None


# --- ATM journal, fee schedule ---------------------------------------------------------------------


@cache
def _atm_journal() -> dict[str, AtmJournal]:
    return {
        r["txn_id"]: AtmJournal(
            r["txn_id"],
            r["atm_id"],
            r["atm_location"],
            Decimal(r["requested_myr"]),
            Decimal(r["dispensed_myr"]),
            r["journal_status"],
        )
        for r in _rows("atm_journal.csv")
    }


def atm_journal(txn_id: str) -> AtmJournal | None:
    return _atm_journal().get(txn_id)


@cache
def fee_schedule() -> tuple[FeeRow, ...]:
    return tuple(
        FeeRow(r["fee_code"], r["fee_name"], r["product"], Decimal(r["amount_myr"]), r["waiver_rule"])
        for r in _rows("fee_schedule.csv")
    )


# --- complaints, labels ----------------------------------------------------------------------------


def _complaint(r: dict[str, str]) -> ComplaintRow:
    return ComplaintRow.model_validate(r)  # pydantic parses received_at and checks the channel


@cache
def _complaints() -> dict[str, ComplaintRow]:
    out: dict[str, ComplaintRow] = {}
    for r in _rows("complaints.csv"):
        c = _complaint(r)
        assert c.complaint_id is not None
        out[c.complaint_id] = c
    return out


def complaints() -> tuple[ComplaintRow, ...]:
    return tuple(_complaints().values())


def complaint(complaint_id: str) -> ComplaintRow:
    return _complaints()[complaint_id]


@cache
def labels() -> dict[str, Label]:
    return {
        r["complaint_id"]: Label(
            r["complaint_id"],
            r["category"],
            r["matched_txn_id"],
            r["outcome"],
            Decimal(r["refund_amount_myr"]),
            r["priority"],
            r["reply_language"],
            r["route"],
        )
        for r in _rows("labels_train.csv")
    }


@cache
def test_ids() -> tuple[str, ...]:
    return tuple(r["complaint_id"] for r in _rows("test_ids.csv"))


# --- bank rules ------------------------------------------------------------------------------------


@cache
def policy_params() -> dict[str, str]:
    """policy_parameters.csv as parameter -> value string (e.g. "AUTO_REFUND_LIMIT_MYR" -> "500.00")."""
    return {r["parameter"]: r["value"] for r in _rows("policy_parameters.csv")}


@cache
def sla_policy() -> dict[str, SlaRow]:
    return {
        r["priority"]: SlaRow(
            r["priority"], int(r["acknowledge_within_hours"]), int(r["resolve_within_business_days"])
        )
        for r in _rows("sla_policy.csv")
    }


@cache
def complaint_policy() -> dict[str, PolicyRow]:
    """Rule text per category, for the decision card."""
    return {
        r["category"]: PolicyRow(
            r["category"],
            r["what_it_covers"],
            r["how_to_find_the_transaction"],
            r["decision_rule"],
            r["base_priority"],
        )
        for r in _rows("complaint_policy.csv")
    }


def clear_caches() -> None:
    """Drop everything loaded so far (tests that change TERATAI_DATA_DIR)."""
    for fn in (
        _customers, _accounts, _txn_index, _atm_journal, fee_schedule, _complaints, labels, test_ids,
        policy_params, sla_policy, complaint_policy,
    ):  # fmt: skip
        fn.cache_clear()
