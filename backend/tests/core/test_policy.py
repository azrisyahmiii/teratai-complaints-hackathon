"""C4 policy engine: every training label on its gold txn + category, then the edge rules (SPEC §4.5, §6)."""

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from teratai import data, policy
from teratai.models import Category, ComplaintRow, MatchResult
from teratai.policy import decide

LABELS = list(data.labels().values())


def _window() -> dict[str, object]:
    return {"start": date(2026, 1, 1), "end": date(2026, 1, 2)}


def match_for(txn_id: str, status: str | None = None) -> MatchResult:
    st = status or ("UNIQUE" if txn_id else "NO_TXN")
    return MatchResult.model_validate(
        {"status": st, "txn_id": txn_id or None, "window": _window(), "candidates": [], "related": {}, "source": "matcher"}
    )


def gold(complaint_id: str):  # type: ignore[no-untyped-def]
    lab = data.labels()[complaint_id]
    cat: Category = lab.category  # type: ignore[assignment]
    return decide(data.complaint(complaint_id), cat, match_for(lab.matched_txn_id))


@pytest.mark.parametrize("lab", LABELS, ids=[lab.complaint_id for lab in LABELS])
def test_gold_label(lab: data.Label) -> None:
    cat: Category = lab.category  # type: ignore[assignment]
    d = decide(data.complaint(lab.complaint_id), cat, match_for(lab.matched_txn_id))
    assert (d.outcome, str(d.refund_myr), d.priority, d.route) == (
        lab.outcome,
        f"{lab.refund_amount:.2f}",
        lab.priority,
        lab.route,
    )
    assert not d.needs_info


# --- DEMO regressions --------------------------------------------------------------------------------


def test_cmp_00165_duplicate_refund() -> None:
    d = gold("CMP-00165")
    assert (d.outcome, d.refund_myr, d.priority, d.route) == ("REFUND", Decimal("46.66"), "P2", "AUTO_RESOLVE")
    assert d.rule_id == "DUPLICATE_CHARGE.REFUND"
    assert d.inputs["sibling"] == "TXN-0115571" and d.inputs["reversed"] == "no"
    assert d.inputs["gap"] == "1m50s"


def test_cmp_00244_atm_shortfall() -> None:
    d = gold("CMP-00244")
    assert (d.outcome, d.refund_myr, d.route) == ("REFUND", Decimal("550.00"), "HUMAN_APPROVAL")
    assert d.calc == "1500.00 − 950.00 = 550.00"


def test_cmp_00387_investigate() -> None:
    d = gold("CMP-00387")
    assert (d.outcome, d.refund_myr, d.priority, d.route) == ("INVESTIGATE", Decimal("0.00"), "P1", "FRAUD_TEAM")
    assert d.inputs["auth_method"] == "3DS-OTP"
    assert "INVESTIGATE" in d.rule_text


def test_cmp_00289_large_refund() -> None:
    d = gold("CMP-00289")
    assert (d.outcome, d.refund_myr, d.route) == ("REFUND", Decimal("4687.10"), "HUMAN_APPROVAL")


# --- edge rules -----------------------------------------------------------------------------------


def test_route_refund_limit_is_above_500() -> None:
    assert policy.route_for("REFUND", Decimal("500.00")) == "AUTO_RESOLVE"
    assert policy.route_for("REFUND", Decimal("500.01")) == "HUMAN_APPROVAL"
    assert policy.route_for("DECLINE", Decimal("0.00")) == "HUMAN_APPROVAL"
    assert policy.route_for("INVESTIGATE", Decimal("0.00")) == "FRAUD_TEAM"
    assert policy.route_for("INFO_ONLY", Decimal("0.00")) == "AUTO_RESOLVE"


def _row(received: datetime) -> ComplaintRow:
    return ComplaintRow(customer_id="CUS-00001", received_at=received, channel="Email", text="x")


@pytest.fixture
def born(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def set_dob(dob: date) -> None:
        c = dataclasses.replace(data.customer("CUS-00001"), date_of_birth=dob)
        monkeypatch.setattr(data, "customer", lambda _cid: c)

    return set_dob


def test_age_65_bump_on_received_date(born) -> None:  # type: ignore[no-untyped-def]
    born(date(1961, 8, 24))  # turns 65 on 2026-08-24
    assert policy.priority_for("DUPLICATE_CHARGE", _row(datetime(2026, 8, 24, 0, 5)))[0] == "P1"  # birthday counts
    assert policy.priority_for("DUPLICATE_CHARGE", _row(datetime(2026, 8, 23, 23, 59)))[0] == "P2"
    assert policy.priority_for("FEE_DISPUTE", _row(datetime(2026, 8, 24, 9, 0)))[0] == "P2"  # P3 -> P2
    assert policy.priority_for("SCAM_TRANSFER", _row(datetime(2026, 8, 24, 9, 0)))[0] == "P1"  # stays P1


def _txn(day: date) -> data.Txn:
    base = next(t for t in data.txns_for("CUS-00001") if t.direction == "DR")
    return dataclasses.replace(base, txn_time=datetime(day.year, day.month, day.day, 3, 0))


def _acc(product: str, opened: date) -> data.Account:
    return dataclasses.replace(data.accounts_for("CUS-00001")[0], product=product, open_date=opened)


def _cust(dob: date) -> data.Customer:
    return dataclasses.replace(data.customer("CUS-00001"), date_of_birth=dob)


def test_debit_fee_waived_at_60_on_charge_date() -> None:
    dob = date(1966, 3, 10)
    assert policy._waived_debit(_txn(date(2026, 3, 10)), _acc("Savings Plus", date(2020, 1, 1)), _cust(dob))
    assert not policy._waived_debit(_txn(date(2026, 3, 9)), _acc("Savings Plus", date(2020, 1, 1)), _cust(dob))


def test_cc_fee_chargeable_on_first_anniversary() -> None:
    acc = _acc("Credit Card Classic", date(2025, 6, 15))
    cust = _cust(date(1990, 1, 1))
    assert policy._waived_first_year(_txn(date(2026, 6, 14)), acc, cust)
    assert not policy._waived_first_year(_txn(date(2026, 6, 15)), acc, cust)


def test_age_on_leap_day_birthday() -> None:
    assert policy.age_on(date(1960, 2, 29), date(2026, 2, 28)) == 65
    assert policy.age_on(date(1961, 2, 28), date(2026, 2, 28)) == 65
    assert policy.age_on(date(1961, 3, 1), date(2026, 2, 28)) == 64


# --- needs-info and service quality ------------------------------------------------------------------


@pytest.mark.parametrize("status", ["NONE", "AMBIGUOUS", "WRONG_CUSTOMER"])
def test_needs_info_by_category(status: str) -> None:
    row = data.complaint("CMP-00165")
    for cat, outcome, route in [
        ("SCAM_TRANSFER", "INVESTIGATE", "FRAUD_TEAM"),
        ("UNAUTHORISED_CARD", "INVESTIGATE", "FRAUD_TEAM"),
        ("DUPLICATE_CHARGE", "DECLINE", "HUMAN_APPROVAL"),
        ("FEE_DISPUTE", "DECLINE", "HUMAN_APPROVAL"),
    ]:
        d = decide(row, cat, match_for("", status))  # type: ignore[arg-type]
        assert d.needs_info and d.refund_myr == Decimal("0.00")
        assert (d.outcome, d.route) == (outcome, route)


def test_service_quality_info_only() -> None:
    d = decide(data.complaint("CMP-00002"), "SERVICE_QUALITY", match_for(""))
    assert (d.outcome, d.refund_myr, d.route, d.needs_info) == ("INFO_ONLY", Decimal("0.00"), "AUTO_RESOLVE", False)


def test_txn_of_another_customer_is_needs_info() -> None:
    other = next(t for t in data.txns_for("CUS-00002") if t.direction == "DR")
    d = decide(data.complaint("CMP-00165"), "FAILED_TRANSFER", match_for(other.txn_id))
    assert d.needs_info


def test_unknown_auth_method_investigates(monkeypatch: pytest.MonkeyPatch) -> None:
    t = dataclasses.replace(next(x for x in data.txns_for("CUS-00001") if x.direction == "DR"), auth_method="Contactless")
    assert policy._unauthorised(t).outcome == "INVESTIGATE"


def test_earlier_identical_none_for_first_charge() -> None:
    sib = data.txn(gold("CMP-00165").inputs["sibling"])
    assert policy.earlier_identical(sib) is None
    assert policy.earlier_identical(data.txn("TXN-0115572")) == sib
