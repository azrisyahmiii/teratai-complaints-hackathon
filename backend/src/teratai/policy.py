"""Policy engine (SPEC §4.5, §6): outcome, refund, priority, route and the rule trace. All code, no LLM.

Money is `Decimal` quantized to 0.01. `decide` is pure: it reads only through `data.py` and `config.py`.
A new category is a new entry in `_RULES` (plus its row in complaint_policy.csv); a new fee waiver is a new
entry in `_FEE_WAIVERS`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from teratai import config, data
from teratai.models import Category, ComplaintRow, Decision, MatchResult, Outcome, Priority, Route

MINUS = "−"  # the minus sign used in `calc` strings, e.g. "1500.00 − 950.00 = 550.00"
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_PRIORITY_UP: dict[str, Priority] = {"P3": "P2", "P2": "P1", "P1": "P1"}
_INVESTIGATE_ON_NEEDS_INFO: frozenset[str] = frozenset({"SCAM_TRANSFER", "UNAUTHORISED_CARD"})


def money(x: Decimal) -> Decimal:
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def age_on(dob: date, day: date) -> int:
    """Whole years on `day`; a birthday that day counts."""
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb -> 1 Mar
        return date(d.year + years, 3, 1)


def earlier_identical(t: data.Txn) -> data.Txn | None:
    """The closest earlier charge by the same customer on the same card, merchant, channel and amount."""
    best: data.Txn | None = None
    for o in data.txns_for(t.customer_id):
        if (o.txn_time, o.txn_id) >= (t.txn_time, t.txn_id):
            break  # txns_for is sorted by (txn_time, txn_id)
        if (
            o.direction == "DR"
            and o.channel == t.channel
            and o.merchant == t.merchant
            and o.amount == t.amount
            and o.card_last4 == t.card_last4
        ):
            best = o
    return best


# --- per-category rules ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    refund: Decimal
    suffix: str  # rule_id = f"{category}.{suffix}"
    inputs: dict[str, str]
    calc: str | None = None


class NeedsInfo(Exception):
    """The evidence cannot support a decision (e.g. the matched row is the wrong kind)."""


def _gap(a: data.Txn, b: data.Txn) -> str:
    secs = int(abs((b.txn_time - a.txn_time).total_seconds()))
    return f"{secs // 60}m{secs % 60:02d}s"


def _duplicate(t: data.Txn) -> Verdict:
    sib = earlier_identical(t)
    if sib is None:
        return Verdict("DECLINE", _ZERO, "DECLINE", {"sibling": "none"})
    gap = t.txn_time - sib.txn_time
    inputs = {"sibling": sib.txn_id, "gap": _gap(sib, t)}
    rev_t, rev_s = data.reversal_of(t.txn_id), data.reversal_of(sib.txn_id)
    inputs["reversed"] = "yes" if (rev_t or rev_s) else "no"
    within = gap <= timedelta(minutes=config.DUPLICATE_WINDOW_MINUTES)
    if within and not (rev_t or rev_s):
        return Verdict("REFUND", money(t.amount), "REFUND", inputs)
    return Verdict("DECLINE", _ZERO, "DECLINE", inputs)


def _failed_transfer(t: data.Txn) -> Verdict:
    rev = data.reversal_of(t.txn_id)
    inputs = {"status": t.status, "reversal": rev.txn_id if rev else "none"}
    if rev:
        inputs["reversed_on"] = rev.txn_time.date().isoformat()
    if t.status == "Failed" and rev is None:
        return Verdict("REFUND", money(t.amount), "REFUND", inputs)
    return Verdict("DECLINE", _ZERO, "DECLINE", inputs)


def _atm(t: data.Txn) -> Verdict:
    j = data.atm_journal(t.txn_id)
    if j is None:
        raise NeedsInfo("no ATM journal row")
    inputs = {"requested": str(j.requested), "dispensed": str(j.dispensed), "journal_status": j.journal_status}
    calc = f"{j.requested} {MINUS} {j.dispensed} = {money(j.shortfall)}"
    if j.dispensed < j.requested:
        return Verdict("REFUND", money(j.shortfall), "REFUND", inputs, calc)
    return Verdict("DECLINE", _ZERO, "DECLINE", inputs, calc)


def _unauthorised(t: data.Txn) -> Verdict:
    inputs = {"auth_method": t.auth_method}
    if t.auth_method == "None":
        return Verdict("REFUND", money(t.amount), "REFUND", inputs)
    return Verdict("INVESTIGATE", _ZERO, "INVESTIGATE", inputs)  # 3DS-OTP, Chip+PIN, or any unknown value


def _scam(t: data.Txn) -> Verdict:
    return Verdict("INVESTIGATE", _ZERO, "INVESTIGATE", {"channel": t.channel})


def _products(fee: data.FeeRow) -> list[str]:
    """fee_schedule `product` may read "Basic Savings; Savings Plus (debit card on the account)"."""
    return [p.strip() for p in re.sub(r"\(.*?\)", "", fee.product).split(";") if p.strip()]


def _waived_debit(t: data.Txn, acc: data.Account, cust: data.Customer) -> str | None:
    age = age_on(cust.date_of_birth, t.txn_time.date())
    return f"age {age} on charge date >= {config.DEBIT_FEE_WAIVER_AGE}" if age >= config.DEBIT_FEE_WAIVER_AGE else None


def _waived_first_year(t: data.Txn, acc: data.Account, cust: data.Customer) -> str | None:
    anniversary = _add_years(acc.open_date, 1)
    # charge on the anniversary day itself is chargeable
    return f"charged {t.txn_time.date()} before first anniversary {anniversary}" if t.txn_time.date() < anniversary else None


_FEE_WAIVERS: dict[str, Callable[[data.Txn, data.Account, data.Customer], str | None]] = {
    "DEBIT_ANNUAL": _waived_debit,
    "CC_ANNUAL_CLASSIC": _waived_first_year,
    "CC_ANNUAL_PLATINUM": _waived_first_year,
}


def _fee(t: data.Txn) -> Verdict:
    acc = data.account(t.account_id)
    cust = data.customer(t.customer_id)
    fee = next(
        (f for f in data.fee_schedule() if t.description.startswith(f.fee_name) and acc.product in _products(f)),
        None,
    )
    if fee is None:
        raise NeedsInfo(f"no fee_schedule row for {t.description!r} on {acc.product}")
    waiver = _FEE_WAIVERS.get(fee.fee_code)
    waived = waiver(t, acc, cust) if waiver else None
    due = _ZERO if waived else fee.amount
    diff = money(t.amount - due)
    inputs = {"fee_code": fee.fee_code, "product": acc.product, "charged": str(money(t.amount)), "due": str(money(due))}
    if waived:
        inputs["waived"] = waived
    calc = f"{money(t.amount)} {MINUS} {money(due)} = {diff}"
    if diff > 0:
        return Verdict("REFUND", diff, "REFUND", inputs, calc)
    return Verdict("DECLINE", _ZERO, "DECLINE", inputs, calc)


_RULES: dict[str, Callable[[data.Txn], Verdict]] = {
    "DUPLICATE_CHARGE": _duplicate,
    "FAILED_TRANSFER": _failed_transfer,
    "ATM_NOT_DISPENSED": _atm,
    "UNAUTHORISED_CARD": _unauthorised,
    "SCAM_TRANSFER": _scam,
    "FEE_DISPUTE": _fee,
}


# --- priority, route -----------------------------------------------------------------------------


def priority_for(category: Category, row: ComplaintRow) -> tuple[Priority, dict[str, str]]:
    """Base priority from complaint_policy.csv, +1 level if age >= VULNERABLE_AGE on the received date."""
    base = data.complaint_policy()[category].base_priority
    age = age_on(data.customer(row.customer_id).date_of_birth, row.received_at.date())
    info = {"base_priority": base, "age_on_received": str(age)}
    if age >= config.VULNERABLE_AGE:
        info["vulnerable_bump"] = "yes"
        return _PRIORITY_UP[base], info
    return base, info  # type: ignore[return-value]


def route_for(outcome: Outcome, refund: Decimal) -> Route:
    if outcome == "INVESTIGATE":
        return "FRAUD_TEAM"
    if outcome == "DECLINE":
        return "HUMAN_APPROVAL"
    if outcome == "REFUND" and refund > config.AUTO_REFUND_LIMIT_MYR:
        return "HUMAN_APPROVAL"
    return "AUTO_RESOLVE"


# --- entry point ---------------------------------------------------------------------------------


def _needs_info(category: Category, priority: Priority, info: dict[str, str], reason: str) -> Decision:
    outcome: Outcome = "INVESTIGATE" if category in _INVESTIGATE_ON_NEEDS_INFO else "DECLINE"
    return Decision(
        outcome=outcome,
        refund_myr=_ZERO,
        priority=priority,
        route=route_for(outcome, _ZERO),
        needs_info=True,
        rule_id="NEEDS_INFO",
        rule_text=f"No unique transaction could be established ({reason}); ask the customer for details. No money moves.",
        inputs={**info, "reason": reason},
        calc=None,
    )


def decide(row: ComplaintRow, category: Category, m: MatchResult) -> Decision:
    priority, pinfo = priority_for(category, row)
    rule_text = data.complaint_policy()[category].decision_rule

    if category == "SERVICE_QUALITY" and m.status in ("NO_TXN", "NONE"):
        return Decision(
            outcome="INFO_ONLY",
            refund_myr=_ZERO,
            priority=priority,
            route="AUTO_RESOLVE",
            needs_info=False,
            rule_id="SERVICE_QUALITY.INFO_ONLY",
            rule_text=rule_text,
            inputs=pinfo,
            calc=None,
        )

    if m.status != "UNIQUE" or not m.txn_id or not data.has_txn(m.txn_id):
        return _needs_info(category, priority, pinfo, f"match status {m.status}")
    t = data.txn(m.txn_id)
    if t.customer_id != row.customer_id:
        return _needs_info(category, priority, pinfo, "matched transaction belongs to another customer")
    rule = _RULES.get(category)
    if rule is None:  # SERVICE_QUALITY with a transaction, or a category without a rule
        return _needs_info(category, priority, pinfo, f"no rule for {category} with a transaction")
    try:
        v = rule(t)
    except NeedsInfo as e:
        return _needs_info(category, priority, pinfo, str(e))

    return Decision(
        outcome=v.outcome,
        refund_myr=v.refund,
        priority=priority,
        route=route_for(v.outcome, v.refund),
        needs_info=False,
        rule_id=f"{category}.{v.suffix}",
        rule_text=rule_text,
        inputs={**v.inputs, **pinfo},
        calc=v.calc,
    )
