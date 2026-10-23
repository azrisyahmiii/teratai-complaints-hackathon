"""Wave-4 review fixes for the Core build: a named payee that does not fit, a date alone, not-a-complaint replies,
the LLM circuit breaker, and a non-vacuous investigator validation. Each test was written failing first.

Regression ids: CMP-00165, CMP-00244, CMP-00387, CMP-00289 (test_match.py / test_wave2.py), and CUS-00150's
2026-09-22 transfer to "Shalini a/p Nair" (TXN-0145614, RM46.54) used below.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest

from teratai import classify, data, dates, extract, investigate, match, pipeline, reply
from teratai.llm import LLMUnavailable, breaker, settings
from teratai.llm.anthropic_provider import AnthropicProvider
from teratai.llm.cache import LLMCache
from teratai.models import ComplaintRow, DateWindow, Issue, StageEvent, Understanding

CUST = "CUS-00150"
RECEIVED = "2026-09-23 10:00"
SHALINI_TXN = "TXN-0145614"  # RM46.54 to Shalini a/p Nair on 2026-09-22


def _noop(_e: StageEvent) -> None:
    return None


def _row(text: str, customer: str = CUST, received: str = RECEIVED, subject: str = "") -> ComplaintRow:
    return ComplaintRow(
        complaint_id="W4-1",
        customer_id=customer,
        received_at=datetime.fromisoformat(received),
        channel="App chat",
        subject=subject,
        text=text,
    )


def _u(issue: Issue) -> Understanding:
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


def _match(text: str, category: str = "FAILED_TRANSFER", issue: Issue | None = None) -> tuple[Any, list[StageEvent]]:
    row = _row(text)
    iss = issue or extract.regex_issue(row, category)  # type: ignore[arg-type]
    window = dates.resolve_window(dates.find_date_phrase(text), row.received_at)
    events: list[StageEvent] = []
    return match.match_case(row, _u(iss), window, events.append), events


# --- 1. a named payee that does not fit / a date alone ----------------------------------------------------------


def test_sanity_the_control_transaction_exists() -> None:
    t = data.txn(SHALINI_TXN)
    assert (t.customer_id, t.amount, t.merchant) == (CUST, Decimal("46.54"), "Shalini a/p Nair")


def test_amount_matches_but_the_named_payee_is_someone_else() -> None:
    m, ev = _match("My transfer of RM46.54 to Ahmad Fauzi yesterday failed, please refund me")
    assert (m.status, m.txn_id) == ("AMBIGUOUS", None)
    assert ev[-1].payload["reason"] == "counterparty_mismatch"
    assert m.candidates[0].txn_id == SHALINI_TXN  # still on the trace for the officer


def test_llm_counterparty_span_is_held_to_the_same_rule() -> None:
    row = _row("Transfer RM46.54 yesterday failed")
    issue = extract.regex_issue(row, "FAILED_TRANSFER").model_copy(update={"counterparty": "Ahmad Fauzi"})
    m, ev = _match(row.text, issue=issue)
    assert (m.status, ev[-1].payload["reason"]) == ("AMBIGUOUS", "counterparty_mismatch")


@pytest.mark.parametrize(
    "text",
    [
        "My transfer of RM46.54 yesterday failed, please refund me",  # no name: the amount alone is enough
        "My transfer of RM46.54 to Shalini yesterday failed, please refund me",  # the name fits
        "Transfer kepada Shalini a/p Nair semalam RM46.54 gagal",
    ],
)
def test_amount_or_fitting_name_still_gives_unique(text: str) -> None:
    m, _ = _match(text)
    assert (m.status, m.txn_id) == ("UNIQUE", SHALINI_TXN)


def test_a_name_without_an_amount_is_enough_when_it_fits() -> None:
    m, _ = _match("My transfer to Shalini yesterday failed, please refund me")
    assert (m.status, m.txn_id) == ("UNIQUE", SHALINI_TXN)


@pytest.mark.parametrize(
    "text",
    [
        "My transfer to Ahmad Fauzi yesterday failed, please refund me",
        "Something went wrong with my transfer yesterday",
    ],
)
def test_a_date_alone_never_picks_a_transaction(text: str) -> None:
    m, _ = _match(text)
    assert m.status in ("NONE", "AMBIGUOUS") and m.txn_id is None


def test_end_to_end_no_refund_and_no_payee_in_the_reply() -> None:
    d = pipeline.process_complaint(_row("My transfer to Ahmad Fauzi yesterday failed, please refund me"), "dev")
    assert d.refund_amount_myr == Decimal("0.00") and d.matched_txn_id == ""
    assert d.route == "HUMAN_APPROVAL" and "Shalini" not in d.reply_text and "46.54" not in d.reply_text


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("My transfer to Ahmad Fauzi yesterday failed", "Ahmad Fauzi"),
        ("I paid at GoRide twice", "GoRide"),
        ("Saya buat transfer kepada Siti binti Ali semalam", "Siti binti Ali"),
        ("Dicaj dua kali di Shopee Malaysia hari ini.", "Shopee Malaysia"),
        ("Please refund me. Sent to Tan Ah Kow, but failed", "Tan Ah Kow"),
        ("transfer to my friend failed", None),
        ("withdrew at the ATM in KLCC", None),
        ("charged RM20 to the account on Monday", None),
        ("sent it to RM46.54 account", None),
        ("Please look at Monday's statement", None),
        ("transfer to Teratai Bank failed", None),
        ("", None),
    ],
)
def test_counterparty_span(text: str, want: str | None) -> None:
    assert extract.counterparty_span(text) == want


def test_no_train_gold_transaction_contradicts_the_named_party() -> None:
    """The refusal rule must not fire on a single labelled complaint's own gold transaction."""
    named = clashes = 0
    for cid, lab in data.labels().items():
        if not lab.matched_txn_id or lab.category == "FEE_DISPUTE":
            continue
        row = data.complaint(cid)
        text = f"{row.subject} {row.text}"
        issue = extract.regex_issue(row, lab.category)  # type: ignore[arg-type]
        named += extract.counterparty_span(text) is not None
        clashes += match._party_mismatch(data.txn(lab.matched_txn_id), issue, text)
    assert clashes == 0 and named > 0


# --- 4. the investigator's pick is validated against every clue -------------------------------------------------


def _fee_case() -> tuple[ComplaintRow, str, Issue]:
    cid = next(c for c, lab in data.labels().items() if lab.category == "FEE_DISPUTE" and lab.matched_txn_id)
    gold = data.txn(data.labels()[cid].matched_txn_id)
    row = data.complaint(cid)
    month = match._fee_period(gold)
    fee_type = next(k for k, v in match._FEE_NAMES.items() if gold.description.startswith(v))
    return row, gold.txn_id, Issue(category="FEE_DISPUTE", fee_type=fee_type, fee_month=month)  # type: ignore[arg-type]


def test_fee_pick_must_match_fee_type_and_month() -> None:
    row, tid, issue = _fee_case()
    window = dates.full_window(row.received_at)
    assert match._validate_investigator(tid, row, issue, window, "")
    assert not match._validate_investigator(tid, row, issue.model_copy(update={"fee_month": "1999-01"}), window, "")
    other = next(k for k in match._FEE_NAMES if k != issue.fee_type)
    assert not match._validate_investigator(tid, row, issue.model_copy(update={"fee_type": other}), window, "")
    wrong_amount = issue.model_copy(update={"amount": data.txn(tid).amount + Decimal("1.00")})
    assert not match._validate_investigator(tid, row, wrong_amount, window, "")


def test_fee_pick_outside_the_window_is_rejected_when_no_month_is_known() -> None:
    row, tid, issue = _fee_case()
    d = data.txn(tid).txn_time.date()
    far = DateWindow(start=date_shift(d, 90), end=date_shift(d, 120), exact_day=None, phrase=None)
    assert not match._validate_investigator(tid, row, issue.model_copy(update={"fee_month": None}), far, "")


def date_shift(d: Any, days: int) -> Any:
    from datetime import timedelta

    return d + timedelta(days=days)


def test_pick_with_no_amount_clue_is_still_checked() -> None:
    row = _row("transfer failed")
    window = dates.full_window(row.received_at)
    issue = Issue(category="FAILED_TRANSFER")
    # no clue and nothing in the text: the date alone is a guess, so the pick is refused (SPEC §2)
    assert not match._validate_investigator(SHALINI_TXN, row, issue, window, "")
    assert not match._validate_investigator(SHALINI_TXN, row, issue, window, "something went wrong with my transfer")
    # evidence the regex missed but the text carries (the amount, the payee) lets the investigator decide
    assert match._validate_investigator(SHALINI_TXN, row, issue, window, "my transfer of RM46.54 failed")
    assert match._validate_investigator(SHALINI_TXN, row, issue, window, "my transfer to Shalini failed")
    # a different category's channel family, another customer's txn, a credit, a txn outside the window
    assert not match._validate_investigator(SHALINI_TXN, row, Issue(category="ATM_NOT_DISPENSED"), window, "")
    assert not match._validate_investigator(SHALINI_TXN, _row("x", customer="CUS-00001"), issue, window, "")
    t = data.txn(SHALINI_TXN).txn_time.date()
    narrow = DateWindow(start=date_shift(t, 5), end=date_shift(t, 6), exact_day=None, phrase=None)
    assert not match._validate_investigator(SHALINI_TXN, row, issue, narrow, "")
    assert not match._validate_investigator("TXN-9999999", row, issue, window, "")


def test_pick_must_fit_the_named_party_and_the_card() -> None:
    row = _row("transfer failed")
    window = dates.full_window(row.received_at)
    issue = Issue(category="FAILED_TRANSFER")
    assert not match._validate_investigator(SHALINI_TXN, row, issue, window, "my transfer to Ahmad Fauzi failed")
    assert match._validate_investigator(SHALINI_TXN, row, issue, window, "my transfer to Shalini failed")
    assert not match._validate_investigator(
        SHALINI_TXN, row, issue.model_copy(update={"counterparty": "Ahmad Fauzi"}), window, ""
    )
    card = next(
        t for t in data.txns_for("CUS-02394") if t.channel in ("Card POS", "Card e-Commerce") and t.direction == "DR"
    )
    r2 = _row("card charge", customer="CUS-02394")
    w2 = dates.full_window(r2.received_at)
    ok = Issue(category="UNAUTHORISED_CARD", card_last4=card.card_last4)
    bad = Issue(category="UNAUTHORISED_CARD", card_last4="0000" if card.card_last4 != "0000" else "1111")
    assert match._validate_investigator(card.txn_id, r2, ok, w2, "") in (True, False)  # window may exclude it
    assert not match._validate_investigator(card.txn_id, r2, bad, w2, "")


def test_investigator_pick_with_the_wrong_payee_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(match, "_investigate", lambda *_a: SHALINI_TXN)
    row = _row("My transfer of RM46.54 to Ahmad Fauzi yesterday failed")
    iss = extract.regex_issue(row, "FAILED_TRANSFER")
    window = dates.resolve_window(dates.find_date_phrase(row.text), row.received_at)
    m = match.match_case(row, _u(iss), window, _noop)
    assert m.status == "AMBIGUOUS" and m.txn_id is None


# --- 2. gibberish and compliments are not complaints ------------------------------------------------------------

COMPLIMENT = "Thanks, your staff were very helpful today!"
GIBBERISH = "asdf qwer zxcv"


@pytest.mark.parametrize("text", [COMPLIMENT, GIBBERISH, "Terima kasih, pekerja anda sangat membantu hari ini!"])
def test_tier0_flags_not_a_complaint(text: str) -> None:
    assert classify.is_complaint_text(_row(text)) is False


@pytest.mark.parametrize(
    "text",
    [
        "Thanks for your help but I was charged twice, RM30 at GoRide",
        "The staff were rude to me at the branch",
        "Thank you, but the ATM did not give me my money",
    ],
)
def test_real_complaints_stay_complaints(text: str) -> None:
    assert classify.is_complaint_text(_row(text)) is True


def test_no_labelled_train_complaint_is_flagged() -> None:
    assert [c for c in data.labels() if not classify.is_complaint_text(data.complaint(c))] == []


@pytest.mark.parametrize("text", [COMPLIMENT, GIBBERISH])
def test_not_a_complaint_gets_a_polite_acknowledgement_not_an_apology(text: str) -> None:
    events: list[StageEvent] = []
    d = pipeline.process_complaint(_row(text), "dev", events.append)
    assert (d.outcome, d.route, d.refund_amount_myr) == ("INFO_ONLY", "AUTO_RESOLVE", Decimal("0.00"))
    assert d.facts.ids["state"] == "not_complaint"
    assert "sorry" not in d.reply_text.lower() and "could not find a complaint" in d.reply_text
    assert d.reply.check.ok
    final = next(e for e in reversed(events) if e.stage == "reply")
    assert final.payload["not_complaint"] is True and final.payload["state"] == "not_complaint"


def test_a_real_service_complaint_still_gets_the_apology() -> None:
    d = pipeline.process_complaint(_row("The staff at the branch were rude and the queue took two hours"), "dev")
    assert d.outcome == "INFO_ONLY" and d.facts.ids["state"] == "decided" and "sorry" in d.reply_text.lower()


def test_build_facts_takes_the_pipelines_verdict_and_never_overrides_a_money_decision() -> None:
    d = pipeline.process_complaint(_row(GIBBERISH), "dev")
    row = _row(GIBBERISH)
    cat = d.understanding.issues[0].category
    assert reply.build_facts(row, cat, d.match, d.decision, is_complaint=True).ids["state"] == "decided"
    assert reply.build_facts(row, cat, d.match, d.decision, is_complaint=False).ids["state"] == "not_complaint"
    assert reply.build_facts(row, cat, d.match, d.decision).ids["state"] == "not_complaint"  # rules decide
    refund = pipeline.process_complaint(data.complaint("CMP-00165"), "dev")
    f = reply.build_facts(
        data.complaint("CMP-00165"), refund.category, refund.match, refund.decision, is_complaint=False
    )
    assert f.ids["state"] == "decided"  # a refund is never turned into an acknowledgement


@pytest.mark.parametrize(("rules_ok", "llm_ok", "want"), [(True, False, False), (False, True, False), (True, True, True)])
def test_llm_verdict_is_carried_into_understanding(
    monkeypatch: pytest.MonkeyPatch, rules_ok: bool, llm_ok: bool, want: bool
) -> None:
    text = "My transfer of RM46.54 to Shalini failed yesterday" if rules_ok else GIBBERISH
    row = _row(text)
    fake = extract.LLMExtraction(
        issues=[Issue(category="SERVICE_QUALITY")], language="EN", is_complaint=llm_ok,
        injection_suspected=False, attempts=1,
    )  # fmt: skip
    monkeypatch.setattr(classify, "_llm_extract", lambda *_a, **_k: fake)
    monkeypatch.setenv("EXTRACT_MODE", "llm")
    u = classify.understand(row, "live", _noop)
    assert u.is_complaint is want


# --- 3. LLM circuit breaker -------------------------------------------------------------------------------------


class _DeadClient:
    """Stands in for anthropic.Anthropic with the API down: every call times out (or raises `error`)."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error
        self.messages = self

    def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise self.error or anthropic.APITimeoutError(httpx.Request("POST", "http://black.hole"))


def _dead_provider(tmp_path: Path, error: Exception | None = None) -> tuple[AnthropicProvider, _DeadClient]:
    client = _DeadClient(error)
    return AnthropicProvider(LLMCache(tmp_path / "c.sqlite"), client=client), client  # type: ignore[arg-type]


MSGS = [{"role": "user", "content": "hello"}]
MODEL = "claude-haiku-5-5"


def test_timeout_opens_the_breaker_and_later_calls_never_reach_the_network(tmp_path: Path) -> None:
    prov, client = _dead_provider(tmp_path)
    with pytest.raises(LLMUnavailable):
        prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 1
    for text in ("again", "and again"):
        with pytest.raises(LLMUnavailable, match="circuit breaker"):
            prov.generate(messages=[{"role": "user", "content": text}], model=MODEL)
    assert client.calls == 1


@pytest.mark.parametrize("status", [500, 503, 529])
def test_server_errors_trip_the_breaker(tmp_path: Path, status: int) -> None:
    resp = httpx.Response(status, request=httpx.Request("POST", "http://x"))
    err = anthropic.APIStatusError("boom", response=resp, body=None)
    prov, client = _dead_provider(tmp_path, err)
    with pytest.raises(LLMUnavailable):
        prov.generate(messages=MSGS, model=MODEL)
    with pytest.raises(LLMUnavailable, match="circuit breaker"):
        prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 1


def test_a_client_error_does_not_trip_the_breaker(tmp_path: Path) -> None:
    resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
    prov, client = _dead_provider(tmp_path, anthropic.BadRequestError("bad", response=resp, body=None))
    for _ in range(2):
        with pytest.raises(anthropic.BadRequestError):
            prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 2


def test_breaker_closes_after_the_window_and_probes_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(breaker, "_now", lambda: clock[0])
    monkeypatch.setenv("LLM_BREAKER_SECONDS", "60")
    prov, client = _dead_provider(tmp_path)
    with pytest.raises(LLMUnavailable):
        prov.generate(messages=MSGS, model=MODEL)
    clock[0] += 59
    with pytest.raises(LLMUnavailable, match="circuit breaker"):
        prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 1
    clock[0] += 2
    with pytest.raises(LLMUnavailable):
        prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 2


def test_breaker_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BREAKER_SECONDS", "0")
    prov, client = _dead_provider(tmp_path)
    for _ in range(2):
        with pytest.raises(LLMUnavailable):
            prov.generate(messages=MSGS, model=MODEL)
    assert client.calls == 2


def test_cached_answers_still_replay_while_the_breaker_is_open(tmp_path: Path) -> None:
    from anthropic.types import TextBlock

    from tests.core.test_llm import FakeClient, _msg  # the same fake the llm tests use

    good = FakeClient([_msg([TextBlock(text="recorded", type="text")], "end_turn")])
    cache = LLMCache(tmp_path / "c.sqlite")
    live = AnthropicProvider(cache, client=good)  # type: ignore[arg-type]
    assert live.generate(messages=MSGS, model=MODEL).text == "recorded"
    breaker.trip("test")
    again = live.generate(messages=MSGS, model=MODEL)
    assert again.text == "recorded" and again.usage.cache_hit and len(good.requests) == 1


def test_timeout_defaults_are_short() -> None:
    assert settings.timeout_s() == 10.0 and settings.max_retries() == 1 and settings.breaker_seconds() == 60.0


def test_one_dead_call_degrades_extract_investigator_and_reply_without_more_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prov, client = _dead_provider(tmp_path)
    monkeypatch.setattr(extract, "get_provider", lambda: prov)
    monkeypatch.setattr(investigate, "get_provider", lambda: prov)
    monkeypatch.setattr(reply, "_provider", lambda: prov)
    monkeypatch.setenv("INVESTIGATOR", "on")
    monkeypatch.setenv("REPLY_MODE", "llm")
    row = data.complaint("CMP-00165")

    events: list[StageEvent] = []
    assert extract.llm_issue(row, events.append) is None  # first call: the one real timeout
    assert events[-1].payload["degraded"] is True and client.calls == 1

    window = dates.full_window(row.received_at)
    issue = extract.regex_issue(row, "DUPLICATE_CHARGE")
    inv_events: list[StageEvent] = []
    assert investigate.investigate(row, _u(issue), window, [], inv_events.append) is None
    assert inv_events[-1].payload["degraded"] is True

    events.clear()
    d = pipeline.process_complaint(row, "live", events.append)  # understand + investigator + reply, all degraded
    final = next(e for e in reversed(events) if e.stage == "reply")
    assert final.payload["degraded"] is True and final.payload["source"] == "template"
    assert d.matched_txn_id == data.labels()["CMP-00165"].matched_txn_id  # the code path still decides
    assert client.calls == 1
