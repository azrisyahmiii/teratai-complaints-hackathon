"""C19: a WRONG_CUSTOMER case gets a non-empty verification reply that reveals nothing about any transaction.

Offline: REPLY_MODE=template, and the provider is a fake that raises if it is ever called.
"""

import re
from typing import Any

import pytest

from teratai import data, dates, extract, match, policy, reply
from teratai.check import check_reply
from teratai.models import ComplaintRow, StageEvent
from tests.core.test_wave2 import _row, _u

CUSTOMER = "CUS-00013"
CASES = [
    "unauthorised RM39.90 StreamMax 28 Sep on my Visa ending 9999",
    "unauthorised RM39.90 StreamMax 28 Sep, kad nombor 9999",
    "My friend's card has an unauthorised RM39.90 StreamMax charge on 28 Sep",
    "Kad kawan saya dicaj RM39.90 di StreamMax pada 28 Sep, bukan saya",
]


def _facts(text: str):
    row: ComplaintRow = _row(text, CUSTOMER)
    issue = extract.regex_issue(row, "UNAUTHORISED_CARD")
    window = dates.resolve_window(dates.find_date_phrase(text), row.received_at)
    events: list[StageEvent] = []
    m = match.match_case(row, _u(issue, "rules", 1.0), window, events.append)
    d = policy.decide(row, "UNAUTHORISED_CARD", m)
    return m, d, reply.build_facts(row, "UNAUTHORISED_CARD", m, d)


class _Boom:
    def generate(self, **_: Any) -> Any:
        raise AssertionError("provider must not be called for wrong_customer")


@pytest.mark.parametrize("text", CASES)
def test_wrong_customer_reply(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLY_MODE", "llm")  # even in LLM mode: no call
    monkeypatch.setattr(reply, "_provider", lambda: _Boom())
    m, d, facts = _facts(text)
    assert m.status == "WRONG_CUSTOMER"
    assert d.outcome == "INVESTIGATE" and d.route != "AUTO_RESOLVE" and d.route == "FRAUD_TEAM"
    assert d.refund_myr == 0 and d.needs_info
    r = reply.write_reply(facts, "live", lambda e: None)
    assert r.text.strip() and r.source == "template"
    assert r.check.ok and check_reply(r.text, facts).ok
    assert "TXN-" not in r.text and not re.search(r"RM\s?\d|\d{4}", r.text)
    assert "refund" not in r.text.lower() or "no decision" in r.text.lower()
    names = {t.merchant.lower() for t in data.txns_for(CUSTOMER) if t.merchant}
    low = r.text.lower()
    assert not [n for n in names if n and "teratai" not in n and n in low]
    assert 15 <= len(r.text.split()) <= 120


def test_non_wrong_customer_decline_never_auto_resolves() -> None:
    # a non-fraud category with a wrong-customer match: DECLINE + HUMAN_APPROVAL
    row = _row(CASES[0], CUSTOMER)
    m, _d, _f = _facts(CASES[0])
    d = policy.decide(row, "DUPLICATE_CHARGE", m)
    assert d.outcome == "DECLINE" and d.route == "HUMAN_APPROVAL" and d.refund_myr == 0


def test_every_train_complaint_gets_a_non_empty_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from teratai.pipeline import process_complaint

    monkeypatch.setenv("REPLY_MODE", "template")
    rows = data.complaints()
    assert len(rows) >= 1750
    empty = []
    for row in rows:
        d = process_complaint(row, run_id="c19", emit=lambda e: None)
        if not d.reply.text.strip() or not d.reply.check.ok:
            empty.append(row.complaint_id)
    assert not empty, empty[:10]

