"""Fact sheet + reply writer (SPEC §4.6-4.7).

`build_facts` turns the decision into the only facts a reply may use. `write_reply` is template-only for now: C10 puts the
LLM draft / redraft in front of `templates.render`, which stays the deterministic fallback.

FactSheet has no field for case state or merchant, so two reserved keys ride in `ids` (the self-check only reads
`TXN-` values there): `ids["state"]` in {decided, needs_info, wrong_customer, not_complaint} and `ids["merchant"]`.
"""

import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from teratai import data
from teratai.check import check_reply
from teratai.lang import reply_language
from teratai.models import (
    Category,
    ComplaintRow,
    Decision,
    Emit,
    FactSheet,
    MatchResult,
    Mode,
    Reply,
    StageEvent,
)
from teratai.policy import earlier_identical, money
from teratai.templates import render

# Malay / Indian patronymic markers give the gender; names without one (e.g. Chinese) get a neutral form
_FEMALE_MARKERS = ("binti", "bte", "bt", "a/p", "d/o")
_MALE_MARKERS = ("bin", "a/l", "s/o")
_HONORIFICS = {"EN": ("Mr", "Ms", ""), "MS": ("Tuan", "Puan", "Tuan/Puan")}  # male, female, unknown

Ids = dict[str, str]
Amounts = dict[str, Decimal]
Dates = dict[str, date]


def honorific(full_name: str, language: str) -> str:
    male, female, unknown = _HONORIFICS[language]
    words = full_name.lower().split()
    if any(w in _FEMALE_MARKERS for w in words):
        return female
    if any(w in _MALE_MARKERS for w in words):
        return male
    return unknown


def _reversal(facts_ids: Ids, amounts: Amounts, dates: Dates, rev: data.Txn | None) -> None:
    if rev is not None:
        facts_ids["reversal"] = rev.txn_id
        amounts["reversal"] = money(rev.amount)
        dates["reversal"] = rev.txn_time.date()


def _duplicate(t: data.Txn, d: Decision, ids: Ids, amounts: Amounts, dates: Dates) -> None:
    sibling = earlier_identical(t)
    if sibling is None:
        return
    ids["sibling"] = sibling.txn_id
    amounts["sibling"] = money(sibling.amount)
    dates["sibling"] = sibling.txn_time.date()
    _reversal(ids, amounts, dates, data.reversal_of(t.txn_id) or data.reversal_of(sibling.txn_id))


def _failed(t: data.Txn, d: Decision, ids: Ids, amounts: Amounts, dates: Dates) -> None:
    _reversal(ids, amounts, dates, data.reversal_of(t.txn_id))


def _atm(t: data.Txn, d: Decision, ids: Ids, amounts: Amounts, dates: Dates) -> None:
    j = data.atm_journal(t.txn_id)
    if j is not None:
        amounts["requested"] = money(j.requested)
        amounts["dispensed"] = money(j.dispensed)
        amounts["shortfall"] = money(j.shortfall)


def _fee(t: data.Txn, d: Decision, ids: Ids, amounts: Amounts, dates: Dates) -> None:
    if "charged" in d.inputs and "due" in d.inputs:
        charged, due = Decimal(d.inputs["charged"]), Decimal(d.inputs["due"])
        amounts["charged"], amounts["due"] = money(charged), money(due)
        if charged > due:
            amounts["difference"] = money(charged - due)


_FILL: dict[str, Callable[..., None]] = {
    "DUPLICATE_CHARGE": _duplicate,
    "FAILED_TRANSFER": _failed,
    "ATM_NOT_DISPENSED": _atm,
    "FEE_DISPUTE": _fee,
}


def build_facts(row: ComplaintRow, category: Category, m: MatchResult, d: Decision) -> FactSheet:
    language, _reason = reply_language(row)
    cust = data.customer(row.customer_id)
    state = "wrong_customer" if m.status == "WRONG_CUSTOMER" else "needs_info" if d.needs_info else "decided"
    ids: Ids = {"state": state}
    amounts: Amounts = {}
    dates: Dates = {}
    if state == "decided" and m.txn_id and data.has_txn(m.txn_id):
        t = data.txn(m.txn_id)
        ids["txn"] = t.txn_id
        if t.merchant and category not in ("ATM_NOT_DISPENSED", "FEE_DISPUTE"):
            ids["merchant"] = t.merchant
        amounts["txn"] = money(t.amount)
        dates["txn"] = t.txn_time.date()
        fill = _FILL.get(category)
        if fill is not None:
            fill(t, d, ids, amounts, dates)
    return FactSheet(
        customer_name=cust.full_name,
        honorific=honorific(cust.full_name, language),
        language=language,
        category=category,
        outcome=d.outcome,
        refund_myr=d.refund_myr,
        ids=ids,
        amounts=amounts,
        dates=dates,
        sla_days=data.sla_policy()[d.priority].resolve_business_days,
    )


def write_reply(facts: FactSheet, mode: Mode, emit: Emit) -> Reply:
    t0 = time.perf_counter()
    text = render(facts)
    check = check_reply(text, facts)
    emit(
        StageEvent(
            stage="reply",
            ok=check.ok,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            payload={
                "source": "template",
                "check_ok": check.ok,
                "issues": [i.model_dump() for i in check.issues],
                "state": facts.ids.get("state", "decided"),
            },
        )
    )
    return Reply(text=text, source="template", check=check, drafts=[text])
