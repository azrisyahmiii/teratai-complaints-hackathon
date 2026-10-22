"""Transaction matcher (SPEC §4.4). Pure code: hard filters, tie-break scores, the unique rule.

`match_case` never guesses: a match must be the only survivor or lead the runner-up by UNIQUE_MARGIN.
Otherwise the status is NONE / AMBIGUOUS, the (stub) investigator gets one chance (§4.4b), and anything it
returns is re-validated against the hard filters here. Weights, tolerances and channel families live in
`config.py`. Clues come from `u.issues[0]`; counterparty names are matched against candidates in code.
"""

import re
import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from teratai import config, data, tools
from teratai.data import Txn
from teratai.models import (
    Candidate,
    ComplaintRow,
    DateWindow,
    Emit,
    Issue,
    MatchResult,
    StageEvent,
    Understanding,
)

_MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

# Fee transaction description prefixes, by Issue.fee_type.
_FEE_NAMES: dict[str, str] = {
    "monthly_service": "Monthly service charge",
    "debit_annual": "Debit card annual fee",
    "cc_annual": "Credit card annual fee",
}
# Fallback when the extractor gave no fee_type: first pattern that hits the complaint text wins.
_FEE_TYPE_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cc_annual", re.compile(r"credit card|kad kredit|\bcc\b", re.IGNORECASE)),
    ("debit_annual", re.compile(r"debit", re.IGNORECASE)),
    ("monthly_service", re.compile(r"service charge|servis|perkhidmatan|monthly|bulanan", re.IGNORECASE)),
)
# Product -> words a complaint uses to name the account (tie-break between two accounts with the same fee).
_PRODUCT_WORDS: dict[str, tuple[str, ...]] = {
    "Basic Savings": ("basic savings", "basic"),
    "Savings Plus": ("savings plus",),
    "Current Account": ("current account", "current", "akaun semasa"),
    "Credit Card Classic": ("classic",),
    "Credit Card Platinum": ("platinum",),
}
_APPROX_ROUND_HALF_STEP_MYR = Decimal(
    "25.00"
)  # customers round to the nearest RM50; TODO(lead): move to config
_PRODUCT_NAMED = config.SCORE_WEIGHTS.get("product_named", 3)  # TODO(lead): add "product_named" to config

# Categories where `card_last4` names the customer's own card (on transfers it is the payee's account).
_CARD_CATEGORIES = frozenset({"DUPLICATE_CHARGE", "UNAUTHORISED_CARD", "ATM_NOT_DISPENSED"})

# Words that appear in many merchant / recipient names and prove nothing on their own.
_NAME_NOISE = frozenset(
    [
        "bin",
        "binti",
        "a/p",
        "a/l",
        "apl",
        "sdn",
        "bhd",
        "ltd",
        "the",
        "and",
        "online",
        "store",
        "shop",
        "travel",
        "bank",
        "transfer",
    ]
)
_WORD = re.compile(r"[a-z0-9/]+")

# The investigator (§4.4b) is C12's. Until then it declines, and the matcher reports NONE / AMBIGUOUS.
Investigator = Callable[[ComplaintRow, Understanding, DateWindow, list[Candidate], Emit], str | None]


def _investigate(
    row: ComplaintRow, u: Understanding, window: DateWindow, candidates: list[Candidate], emit: Emit
) -> str | None:
    return None


# --- scoring helpers -------------------------------------------------------------------------------


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) >= 3}


def counterparty_hit(merchant: str, clue: str | None, text: str) -> bool:
    """Case-insensitive token / substring hit of a candidate's merchant against the clue, else the text.

    `paycoin` is a hit for `PAYCOIN LTD`; `shalini` for `Shalini a/p Nair`. Name particles never count.
    """
    m = merchant.lower().strip()
    if not m:
        return False
    sources = [clue, text] if clue else [text]
    sig = {w for w in _tokens(m) if w not in _NAME_NOISE}
    for src in sources:
        if not src:
            continue
        s = src.lower()
        if m in s or (clue is not None and src is clue and s.strip() and s.strip() in m):
            return True
        if sig & _tokens(s):
            return True
    return False


def _date_score(t: Txn, window: DateWindow) -> tuple[str, int] | None:
    d = t.txn_time.date()
    if window.exact_day is not None and d == window.exact_day:
        return "date_exact_day", config.SCORE_WEIGHTS["date_exact_day"]
    # An exact day is searched over day-1..day+1 for posting lag; those slack days are not "in the range".
    if window.exact_day is None and window.start <= d <= window.end:
        return "date_in_range", config.SCORE_WEIGHTS["date_in_range"]
    return None


def _score(t: Txn, issue: Issue, window: DateWindow, text: str) -> Candidate:
    w = config.SCORE_WEIGHTS
    b: dict[str, int] = {}
    if issue.amount is not None and tools.amount_matches(t.amount, issue.amount):
        b["amount_exact"] = w["amount_exact"]
    if counterparty_hit(t.merchant, issue.counterparty, text):
        b["counterparty"] = w["counterparty"]
    ds = _date_score(t, window)
    if ds:
        b[ds[0]] = ds[1]
    if issue.card_last4 and issue.card_last4 in (t.card_last4, t.counterparty_account[-4:]):
        b["card_last4"] = w["card_last4"]  # a card, or "account ending ..." on a transfer
    return Candidate(txn_id=t.txn_id, score=sum(b.values()), breakdown=b)


# --- candidate generation per category -------------------------------------------------------------


def _amount_filter(issue: Issue) -> tuple[Decimal | None, Decimal | None]:
    """(amount, tol) for `find_transactions`: exact, or max(5%, RM25) when the customer is approximate."""
    if issue.amount is None:
        return None, None
    if issue.amount_approx:
        floor = max(config.AMOUNT_APPROX_MIN_MYR, _APPROX_ROUND_HALF_STEP_MYR)
        return issue.amount, max(issue.amount * config.AMOUNT_APPROX_PCT, floor)
    return issue.amount, None


def _survivors(row: ComplaintRow, issue: Issue, window: DateWindow) -> list[Txn]:
    """Hard filters (SPEC §4.4). Customers round approximate amounts to the nearest RM50 ("about RM250" for
    RM227.11), which max(5%, RM20) misses, so approximate amounts use max(5%, RM25). A wider net can only
    add candidates, and the unique rule turns a tie into AMBIGUOUS rather than a guess."""
    amount, tol = _amount_filter(issue)
    return tools.find_transactions(
        row.customer_id, window.start, window.end, config.CHANNEL_FAMILIES[issue.category],
        amount=amount, tol=tol,
    )  # fmt: skip


def _duplicate_pick(t: Txn, group: list[Txn]) -> tuple[bool, Txn | None, int]:
    """(has predecessor, predecessor, gap in minutes) of `t` inside its identical-charge group."""
    i = group.index(t)
    if i == 0:
        return False, None, 0
    pred = group[i - 1]
    return True, pred, int((t.txn_time - pred.txn_time).total_seconds() // 60)


def _duplicate_candidates(row: ComplaintRow, issue: Issue, window: DateWindow) -> dict[str, Txn | None]:
    """Later charge of each identical group -> its earlier sibling (SPEC §4.4 DUPLICATE_CHARGE).

    Per group of identical charges (same card, merchant, amount): the latest charge whose predecessor is
    within DUPLICATE_LATEST_GAP_MINUTES, else the latest charge that has a predecessor. With no identical
    sibling anywhere, the plain survivors stand (the policy then declines).
    """
    surv = _survivors(row, issue, window)
    family = set(config.CHANNEL_FAMILIES["DUPLICATE_CHARGE"])
    all_debits = [t for t in data.txns_for(row.customer_id) if t.direction == "DR" and t.channel in family]
    groups: dict[tuple[str, str, Decimal], list[Txn]] = {}
    for t in all_debits:
        groups.setdefault((t.card_last4, t.merchant, t.amount), []).append(t)
    picked: dict[str, Txn | None] = {}
    seen: set[tuple[str, str, Decimal]] = set()
    for t in surv:
        key = (t.card_last4, t.merchant, t.amount)
        if key in seen:
            continue
        seen.add(key)
        group = groups[key]
        in_window = [s for s in surv if (s.card_last4, s.merchant, s.amount) == key]
        with_pred = [(s, *_duplicate_pick(s, group)[1:]) for s in in_window if _duplicate_pick(s, group)[0]]
        close = [x for x in with_pred if x[2] <= config.DUPLICATE_LATEST_GAP_MINUTES]
        pool = close or with_pred
        if pool:
            best = pool[-1]
            picked[best[0].txn_id] = best[1]
    if not picked:
        picked = {t.txn_id: None for t in surv}
    return picked


def _infer_fee_type(issue: Issue, text: str) -> str | None:
    if issue.fee_type:
        return issue.fee_type
    for fee_type, pat in _FEE_TYPE_HINTS:
        if pat.search(text):
            return fee_type
    return None


def _fee_period(t: Txn) -> str:
    """'YYYY-MM' a fee belongs to: the month in a monthly-charge description, else the charge month."""
    m = re.search(r"([A-Za-z]{3}) (\d{4})$", t.description)
    if m and m.group(1).lower() in _MONTH_ABBR:
        return f"{m.group(2)}-{_MONTH_ABBR.index(m.group(1).lower()) + 1:02d}"
    return t.txn_time.strftime("%Y-%m")


def _fee_candidates(row: ComplaintRow, issue: Issue, window: DateWindow, text: str) -> list[Candidate]:
    w = config.SCORE_WEIGHTS
    fee_type = _infer_fee_type(issue, text)
    prefix = _FEE_NAMES.get(fee_type) if fee_type else None
    fees = tools.find_transactions(
        row.customer_id, date.min, date.max, config.CHANNEL_FAMILIES["FEE_DISPUTE"], description_prefix=prefix
    )
    if issue.fee_month:
        fees = [t for t in fees if _fee_period(t) == issue.fee_month]
    else:
        fees = [t for t in fees if window.start <= t.txn_time.date() <= window.end]
    low = text.lower()
    out: list[Candidate] = []
    for t in fees:
        b: dict[str, int] = {}
        if prefix:
            b["fee_type_month"] = w["fee_type_month"]
        if issue.amount is not None and tools.amount_matches(t.amount, issue.amount):
            b["amount_exact"] = w["amount_exact"]
        product = data.account(t.account_id).product
        if any(word in low for word in _PRODUCT_WORDS.get(product, ())):
            b["product_named"] = _PRODUCT_NAMED
        out.append(Candidate(txn_id=t.txn_id, score=sum(b.values()), breakdown=b))
    return out


# --- decision --------------------------------------------------------------------------------------


def _rank(cands: list[Candidate]) -> list[Candidate]:
    """Best score first; equal scores keep txn_id order, so the result is deterministic."""
    return sorted(cands, key=lambda c: (-c.score, c.txn_id))


def _decide(cands: list[Candidate]) -> tuple[str, str | None]:
    """Unique rule: the only survivor, or a top score at least UNIQUE_MARGIN above the runner-up."""
    if not cands:
        return "NONE", None
    if len(cands) == 1 or cands[0].score >= cands[1].score + config.UNIQUE_MARGIN:
        return "UNIQUE", cands[0].txn_id
    return "AMBIGUOUS", None


def _related(txn_id: str, sibling: Txn | None) -> dict[str, str]:
    rel: dict[str, str] = {}
    if sibling is not None:
        rel["sibling"] = sibling.txn_id
    rev = data.reversal_of(txn_id) or (data.reversal_of(sibling.txn_id) if sibling else None)
    if rev is not None:
        rel["reversal"] = rev.txn_id
    if data.atm_journal(txn_id) is not None:
        rel["journal"] = txn_id
    return rel


def _validate_investigator(txn_id: str, row: ComplaintRow, issue: Issue, window: DateWindow) -> bool:
    """The investigator's pick must pass every hard filter, or it is ignored (SPEC §4.4b)."""
    if not data.has_txn(txn_id):
        return False
    t = data.txn(txn_id)
    if t.customer_id != row.customer_id or t.direction != "DR":
        return False
    if t.channel not in config.CHANNEL_FAMILIES[issue.category]:
        return False
    if issue.category == "FEE_DISPUTE":
        return True
    if not (window.start <= t.txn_time.date() <= window.end):
        return False
    amount, tol = _amount_filter(issue)
    return amount is None or tools.amount_matches(t.amount, amount, tol=tol)


def _run(row: ComplaintRow, u: Understanding, window: DateWindow, emit: Emit) -> MatchResult:
    issue = u.issues[0]
    text = f"{row.subject} {row.text}"

    def result(status: str, txn_id: str | None, cands: list[Candidate], rel: dict[str, str]) -> MatchResult:
        return MatchResult.model_validate(
            {"status": status, "txn_id": txn_id, "window": window, "candidates": cands, "related": rel,
             "source": "matcher"}
        )  # fmt: skip

    if issue.category == "SERVICE_QUALITY":
        return result("NO_TXN", None, [], {})
    if (
        issue.card_last4
        and issue.category in _CARD_CATEGORIES
        and issue.card_last4 not in tools.owned_card_last4(row.customer_id)
    ):
        return result("WRONG_CUSTOMER", None, [], {})

    siblings: dict[str, Txn | None] = {}
    if issue.category == "FEE_DISPUTE":
        cands = _fee_candidates(row, issue, window, text)
    elif issue.category == "DUPLICATE_CHARGE":
        siblings = _duplicate_candidates(row, issue, window)
        cands = [_score(data.txn(tid), issue, window, text) for tid in siblings]
    else:
        cands = [_score(t, issue, window, text) for t in _survivors(row, issue, window)]
    cands = _rank(cands)
    status, txn_id = _decide(cands)

    if status != "UNIQUE":
        picked = _investigate(row, u, window, cands, emit)
        if picked and _validate_investigator(picked, row, issue, window):
            if all(c.txn_id != picked for c in cands):
                cands.append(Candidate(txn_id=picked, score=0, breakdown={"investigator": 0}))
            r = result("UNIQUE", picked, cands, _related(picked, siblings.get(picked)))
            return r.model_copy(update={"source": "investigator"})

    rel = _related(txn_id, siblings.get(txn_id)) if txn_id else {}
    return result(status, txn_id, cands, rel)


def match_case(row: ComplaintRow, u: Understanding, window: DateWindow, emit: Emit) -> MatchResult:
    """Find the disputed transaction (SPEC §4.4). Emits one `match` StageEvent with candidates and scores."""
    t0 = time.perf_counter()
    m = _run(row, u, window, emit)
    issue = u.issues[0]
    emit(
        StageEvent(
            stage="match",
            ok=m.status in ("UNIQUE", "NO_TXN"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            payload={
                "status": m.status,
                "txn_id": m.txn_id,
                "source": m.source,
                "category": issue.category,
                "window": {
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                    "exact_day": window.exact_day.isoformat() if window.exact_day else None,
                    "phrase": window.phrase,
                },
                "candidates": [c.model_dump() for c in m.candidates],
                "related": m.related,
            },
        )
    )
    return m
