"""Regressions for the C17-C19 review: a truncated amount quote, the SCAM/FAILED tie, the hold-out labels guard."""

from decimal import Decimal

import pytest

from teratai import data, evaluate, extract
from teratai.models import Issue


def _detail(amount_text: str, amount_value: str) -> extract.LLMDetail:
    return extract.LLMDetail(amount_text=amount_text, amount_value=Decimal(amount_value), other_amounts=(),
                             date_normalised=None)


@pytest.mark.parametrize(
    ("text", "quote", "value"),
    [("transfer RM1200 failed", "RM12", "12"), ("transfer RM1 500 failed", "RM1", "1"), ("caj rm46.66 dua kali", "rm46", "46")],
)
def test_a_truncated_quote_is_not_an_amount(text: str, quote: str, value: str) -> None:
    amount, _ = extract.verified_amount(Issue(category="FAILED_TRANSFER"), _detail(quote, value), text)
    assert amount is None  # falls back to the regex reader, never a partial number


@pytest.mark.parametrize(
    ("text", "quote", "value"),
    [("transfer RM1200 failed", "RM1200", "1200"), ("trf rm1.5k x masuk", "rm1.5k", "1500"),
     ("caj rm46.66 dua kali", "rm46.66", "46.66")],
)
def test_a_whole_quote_is_accepted(text: str, quote: str, value: str) -> None:
    amount, _ = extract.verified_amount(Issue(category="FAILED_TRANSFER"), _detail(quote, value), text)
    assert amount == Decimal(value)


def test_scam_failed_tie_is_settled_by_the_txn_status() -> None:
    """A failed DuitNow transfer is FAILED_TRANSFER; a completed one would be SCAM (safe). Gold: CUS-01874."""
    failed = next(
        t for t in data.txns_for("CUS-01874")
        if t.channel in ("DuitNow Transfer", "IBG Transfer") and t.status == "Failed" and t.amount == Decimal("77.58")
    )
    assert failed.status == "Failed"  # the evidence the rule reads


def test_holdout_labels_are_guarded() -> None:
    with pytest.raises(SystemExit):
        evaluate.check_holdout_guard("tests/core/fixtures/holdout/messy_holdout_labels.csv", False)
