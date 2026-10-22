"""Matcher tests (SPEC §4.4): named regressions, scenario tests, and a full run over the 1,750 training labels.

The clue extractor below is a TEST-LOCAL stand-in for C6's real extractor (amount, approx marker, card last 4,
fee type + month). It exists only to measure the matcher against `matched_txn_id` with the gold category.
Run the report with `cd backend && uv run python tests/core/test_match.py`.
"""

import re
from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from teratai import data, dates, match, tools
from teratai.models import ComplaintRow, Issue, MatchResult, StageEvent, Understanding

# --- test-local clue extraction --------------------------------------------------------------------

_AMOUNT = re.compile(r"(?:RM|MYR)\s?([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s?ringgit", re.IGNORECASE)
_APPROX = re.compile(
    r"about|around|approx|roughly|lebih kurang|kira-kira|sekitar|almost|nearly|dalam", re.IGNORECASE
)
_CARD = re.compile(r"(?:ending|last 4|last four|berakhir|akhir|hujung)\D{0,20}(\d{4})", re.IGNORECASE)
_MONTH_NAMES = (
    "jan", "feb", "mar|mac", "apr", "may|mei", "jun", "jul", "aug|ogos", "sep", "oct|okt", "nov", "dec|dis",
)  # fmt: skip
_FEE_MONTH = re.compile(r"(?:for|in|during|bagi bulan|bulan|untuk)\s+([a-z]{3,9})\b", re.IGNORECASE)
_FEE_TYPES = (
    ("cc_annual", re.compile(r"credit card annual|kad kredit", re.IGNORECASE)),
    ("debit_annual", re.compile(r"debit card annual|kad debit", re.IGNORECASE)),
    ("monthly_service", re.compile(r"monthly service|perkhidmatan bulanan", re.IGNORECASE)),
)


def _month_index(word: str) -> int | None:
    w = word.lower()[:3]
    for i, alts in enumerate(_MONTH_NAMES):
        if w in alts.split("|"):
            return i + 1
    return None


def clues(row: ComplaintRow, category: str) -> Issue:
    text = f"{row.subject} {row.text}"
    amount: Decimal | None = None
    approx = False
    m = _AMOUNT.search(text)
    if m:
        amount = Decimal((m.group(1) or m.group(2)).replace(",", "").rstrip("."))
        approx = bool(_APPROX.search(text[max(0, m.start() - 25) : m.start()]))
    card = _CARD.search(text)
    fee_type = next((t for t, p in _FEE_TYPES if p.search(text)), None) if category == "FEE_DISPUTE" else None
    fee_month = None
    if fee_type:
        for fm in _FEE_MONTH.finditer(text):
            idx = _month_index(fm.group(1))
            if idx is not None:
                year = row.received_at.year if idx <= row.received_at.month else row.received_at.year - 1
                fee_month = f"{year}-{idx:02d}"
                break
    return Issue.model_validate(
        {
            "category": category,
            "amount": amount,
            "amount_approx": approx,
            "card_last4": card.group(1) if card else None,
            "fee_type": fee_type,
            "fee_month": fee_month,
        }
    )


def understanding(issue: Issue) -> Understanding:
    return Understanding(
        issues=[issue],
        top3=[(issue.category, 1.0)],
        source="rules",
        language="EN",
        language_reason="test",
        is_complaint=True,
        injection_suspected=False,
        scam_cue=False,
    )


def _noop(_e: StageEvent) -> None:
    return None


def run_match(complaint_id: str, category: str | None = None) -> MatchResult:
    row = data.complaint(complaint_id)
    cat = category or data.labels()[complaint_id].category
    window = dates.resolve_window(dates.find_date_phrase(f"{row.subject} {row.text}"), row.received_at)
    return match.match_case(row, understanding(clues(row, cat)), window, _noop)


# --- named regressions -----------------------------------------------------------------------------


@pytest.mark.parametrize("cid", ["CMP-00165", "CMP-00244", "CMP-00387", "CMP-00289"])
def test_demo_cases_match_gold(cid: str) -> None:
    m = run_match(cid)
    assert m.status == "UNIQUE"
    assert m.txn_id == data.labels()[cid].matched_txn_id


def test_duplicate_picks_later_of_pair_and_links_sibling() -> None:
    m = run_match("CMP-00165")
    assert m.txn_id == "TXN-0115572"
    assert m.related["sibling"] == "TXN-0115571"
    assert "reversal" not in m.related


def test_atm_links_journal() -> None:
    m = run_match("CMP-00244")
    assert m.txn_id == "TXN-0088211"
    assert m.related["journal"] == "TXN-0088211"


def test_emits_one_match_event_with_candidates() -> None:
    events: list[StageEvent] = []
    row = data.complaint("CMP-00165")
    window = dates.resolve_window("hari Selasa lepas", row.received_at)
    match.match_case(row, understanding(clues(row, "DUPLICATE_CHARGE")), window, events.append)
    assert [e.stage for e in events] == ["match"]
    assert events[0].payload["status"] == "UNIQUE"
    assert events[0].payload["candidates"][0]["txn_id"] == "TXN-0115572"


# Gold transaction outside the naive max(5%, RM20) tolerance: customers round "about RM250" for RM227.11.
GOLD_OUTSIDE_TOLERANCE = [
    "CMP-00018", "CMP-00295", "CMP-00692", "CMP-00694", "CMP-00962", "CMP-00993",
    "CMP-01550", "CMP-01948", "CMP-01953", "CMP-02001", "CMP-02256", "CMP-02271",
]  # fmt: skip
# Same amount and merchant on adjacent days: only the exact-day hit separates them.
ADJACENT_DAY_TWINS = ["CMP-00309", "CMP-00889"]


@pytest.mark.parametrize("cid", GOLD_OUTSIDE_TOLERANCE + ADJACENT_DAY_TWINS)
def test_gold_missing_regressions(cid: str) -> None:
    m = run_match(cid)
    assert m.status == "UNIQUE"
    assert m.txn_id == data.labels()[cid].matched_txn_id


# --- scenarios -------------------------------------------------------------------------------------


def test_service_quality_has_no_txn() -> None:
    row = data.complaint("CMP-00002")
    u = understanding(clues(row, "SERVICE_QUALITY"))
    m = match.match_case(row, u, dates.full_window(row.received_at), _noop)
    assert (m.status, m.txn_id, m.candidates) == ("NO_TXN", None, [])


def test_card_not_owned_is_wrong_customer() -> None:
    row = data.complaint("CMP-00387")
    issue = clues(row, "UNAUTHORISED_CARD").model_copy(update={"card_last4": "0000"})
    assert "0000" not in tools.owned_card_last4(row.customer_id)
    m = match.match_case(row, understanding(issue), dates.full_window(row.received_at), _noop)
    assert (m.status, m.txn_id) == ("WRONG_CUSTOMER", None)


def test_unmatchable_amount_is_none() -> None:
    row = data.complaint("CMP-00244")
    issue = clues(row, "ATM_NOT_DISPENSED").model_copy(
        update={"amount": Decimal("1234567.89"), "amount_approx": False}
    )
    m = match.match_case(row, understanding(issue), dates.full_window(row.received_at), _noop)
    assert (m.status, m.txn_id, m.candidates) == ("NONE", None, [])


def test_tie_is_ambiguous_and_keeps_candidates() -> None:
    row = data.complaint("CMP-00244")
    issue = Issue(category="ATM_NOT_DISPENSED")  # no clues at all: every ATM debit in 45 days survives
    m = match.match_case(row, understanding(issue), dates.full_window(row.received_at), _noop)
    assert m.status == "AMBIGUOUS" and m.txn_id is None
    assert len(m.candidates) > 1


def test_investigator_pick_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    row = data.complaint("CMP-00244")
    issue = Issue(category="ATM_NOT_DISPENSED")
    window = dates.full_window(row.received_at)
    gold = data.labels()["CMP-00244"].matched_txn_id

    monkeypatch.setattr(match, "_investigate", lambda *_a: gold)
    m = match.match_case(row, understanding(issue), window, _noop)
    assert (m.status, m.txn_id, m.source) == ("UNIQUE", gold, "investigator")

    other_customer = next(t.txn_id for t in data.txns_for("CUS-00001") if t.channel == "ATM Withdrawal")
    monkeypatch.setattr(match, "_investigate", lambda *_a: other_customer)
    m = match.match_case(row, understanding(issue), window, _noop)
    assert m.status == "AMBIGUOUS" and m.source == "matcher"


def test_counterparty_hit() -> None:
    assert match.counterparty_hit("PAYCOIN LTD", "paycoin", "")
    assert match.counterparty_hit("Shalini a/p Nair", None, "transfer to shalini yesterday")
    assert not match.counterparty_hit("Ravi a/l Velu", None, "transfer to Aisyah binti Hassan")
    assert not match.counterparty_hit("Hakim bin Ibrahim", None, "to Faris bin Salleh")


def test_find_transactions_tool_returns_strings() -> None:
    out = tools.call_tool(
        "find_transactions",
        {"customer_id": "CUS-02394", "start": "2026-07-01", "end": "2026-07-20", "channels": ["ATM Withdrawal"],
         "amount": "1500.00"},
    )  # fmt: skip
    assert out["count"] >= 1
    assert all(isinstance(t["amount_myr"], str) for t in out["transactions"])
    assert "error" in tools.call_tool("find_transactions", {"customer_id": "CUS-02394"})
    assert {s["name"] for s in tools.tool_specs()} == set(tools.handlers())


# --- full training run -----------------------------------------------------------------------------

Miss = tuple[str, str, str, str]  # complaint id, status, got, gold


def evaluate() -> tuple[Counter[str], Counter[str], dict[str, list[Miss]]]:
    """Per-category totals / correct, and the misses."""
    total: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    miss: dict[str, list[Miss]] = defaultdict(list)
    for cid, lab in data.labels().items():
        m = run_match(cid)
        got = m.txn_id or ""
        total[lab.category] += 1
        if got == lab.matched_txn_id:
            ok[lab.category] += 1
        else:
            miss[lab.category].append((cid, m.status, got, lab.matched_txn_id))
    return total, ok, miss


def test_missing_clues_never_give_a_wrong_match() -> None:
    """Drop the amount, or the date: the matcher may say AMBIGUOUS but must never pick a wrong transaction."""
    wrong: list[str] = []
    for cid, lab in data.labels().items():
        row = data.complaint(cid)
        issue = clues(row, lab.category)
        text = f"{row.subject} {row.text}"
        variants = (
            (issue.model_copy(update={"amount": None, "amount_approx": False}), dates.find_date_phrase(text)),
            (issue, None),
        )
        for iss, phrase in variants:
            m = match.match_case(
                row, understanding(iss), dates.resolve_window(phrase, row.received_at), _noop
            )
            if m.txn_id and m.txn_id != lab.matched_txn_id:
                wrong.append(cid)
    assert wrong == []


def test_train_accuracy_floor() -> None:
    total, ok, miss = evaluate()
    wrong = [x for xs in miss.values() for x in xs if x[2]]
    acc = sum(ok.values()) / sum(total.values())
    assert acc >= 0.97, f"{acc:.3%}"
    assert len(wrong) == 0, wrong[:5]


if __name__ == "__main__":
    t, o, ms = evaluate()
    for cat in sorted(t):
        print(f"{cat:20s} {o[cat]:4d}/{t[cat]:4d} = {o[cat] / t[cat]:.2%}")
    print(f"{'ALL':20s} {sum(o.values()):4d}/{sum(t.values()):4d} = {sum(o.values()) / sum(t.values()):.2%}")
    for cat, xs in ms.items():
        print(f"\n--- {cat}: {len(xs)} misses")
        for x in xs[:40]:
            print("  ", x)
