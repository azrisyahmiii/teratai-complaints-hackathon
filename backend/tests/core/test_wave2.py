"""Wave-2 review fixes for C4-C6: third-party / card clues, tool scope, MS loanwords, low-confidence guesses,
lone survivors without a clue, OOF keyed by text, romance cues. Each test was written failing first."""

from datetime import datetime

import pytest

from teratai import classify, data, dates, extract, lang, match, tools
from teratai.models import ComplaintRow, DateWindow, Issue, StageEvent, Understanding

# --- helpers ---------------------------------------------------------------------------------------------


def _noop(_e: StageEvent) -> None:
    return None


def _row(text: str, customer_id: str = "CUS-00013", received: str = "2026-09-30 10:15") -> ComplaintRow:
    return ComplaintRow(
        customer_id=customer_id, received_at=datetime.fromisoformat(received), channel="App chat", text=text
    )


def _u(issue: Issue, source: str = "rules", conf: float = 1.0) -> Understanding:
    return Understanding(
        issues=[issue],
        top3=[(issue.category, conf)],
        source=source,  # type: ignore[arg-type]
        language="EN",
        language_reason="test",
        is_complaint=True,
        injection_suspected=False,
        scam_cue=False,
    )


def _match_text(text: str, category: str, source: str = "rules", conf: float = 1.0, customer: str = "CUS-00013"):
    row = _row(text, customer)
    issue = extract.regex_issue(row, category)  # type: ignore[arg-type]
    window = dates.resolve_window(dates.find_date_phrase(text), row.received_at)
    events: list[StageEvent] = []
    m = match.match_case(row, _u(issue, source, conf), window, events.append)
    return m, events


# --- 1. card on a card the customer does not own / third party -------------------------------------------


@pytest.mark.parametrize(
    "text, want",
    [
        ("unauthorised RM39.90 StreamMax 28 Sep on my Visa ending 9999", "9999"),
        ("unauthorised RM39.90 StreamMax 28 Sep, kad nombor 9999", "9999"),
        ("charge on my Mastercard 4321 that I did not make", "4321"),
        ("my debit card no. 8888 was used", "8888"),
        ("kad kredit saya berakhir 1234 dicaj dua kali", "1234"),
        ("card ending in 2832", "2832"),
        ("the card number is 7777", "7777"),
        ("last 4 digits of the card: 5555", "5555"),
        ("charged twice (kad hujung 3271)", "3271"),
        ("it was on ending 4545 yesterday", "4545"),
    ],
)
def test_card_last4_wider_forms(text: str, want: str) -> None:
    assert extract.card_last4(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "charged on 28 Sep 2026 at 1030 hrs",
        "charged RM1500 twice and RM 2000 again",
        "my card was blocked in 2026",
        "paid by card on 2026-09-28",
        "transfer to account ending 1234",
        "transfer ke akaun berakhir 7865",
        "call me at 03-1234 5678 about the card",
        "the credit of 1500 ringgit never came",
        "debit RM 1234.56 twice",
    ],
)
def test_card_last4_ignores_years_amounts_times_and_accounts(text: str) -> None:
    assert extract.card_last4(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "My friend's card was used for RM39.90 at StreamMax",
        "this is my wife's card and she was charged twice",
        "my husband's account shows an unauthorised charge",
        "it is my son's debit card",
        "my mother's card was charged",
        "Kad kawan saya dicaj dua kali",
        "ada caj pada akaun adik saya",
        "kad isteri saya digunakan tanpa kebenaran",
        "I am writing on behalf of my uncle",
        "bagi pihak ayah saya, kad beliau dicaj",
        "the card belongs to my colleague",
    ],
)
def test_third_party_cue_fires(text: str) -> None:
    assert extract.third_party_cue(text)


@pytest.mark.parametrize(
    "text",
    [
        "I sent RM100 to my friend's account but the transfer failed",
        "transfer ke akaun kawan saya gagal",
        "kawan online minta RM1000 emergency, saya transfer",
        "I was charged twice at GoRide yesterday",
        "my card was charged RM50 twice",
        "my wife told me the app was down",
    ],
)
def test_third_party_cue_stays_quiet(text: str) -> None:
    assert not extract.third_party_cue(text)


def test_card_not_owned_in_text_is_wrong_customer_not_refund() -> None:
    """CUS-00013 owns card 1972 (and 0936). 'Visa ending 9999' is not theirs: no decision on this card."""
    assert "9999" not in tools.owned_card_last4("CUS-00013")
    for text in (
        "unauthorised RM39.90 StreamMax 28 Sep on my Visa ending 9999",
        "unauthorised RM39.90 StreamMax 28 Sep, kad nombor 9999",
    ):
        m, _ = _match_text(text, "UNAUTHORISED_CARD")
        assert (m.status, m.txn_id) == ("WRONG_CUSTOMER", None), text


def test_friends_card_is_wrong_customer() -> None:
    m, _ = _match_text("My friend's card has an unauthorised RM39.90 StreamMax charge on 28 Sep", "UNAUTHORISED_CARD")
    assert (m.status, m.txn_id) == ("WRONG_CUSTOMER", None)
    m, _ = _match_text("Kad kawan saya dicaj RM39.90 di StreamMax pada 28 Sep, bukan saya", "UNAUTHORISED_CARD")
    assert m.status == "WRONG_CUSTOMER"


def test_own_card_still_matches() -> None:
    m, _ = _match_text("unauthorised RM39.90 StreamMax on 28 Sep on my card ending 1972", "UNAUTHORISED_CARD")
    assert (m.status, m.txn_id) == ("UNIQUE", "TXN-0151527")


def test_no_third_party_or_foreign_card_cue_in_train() -> None:
    """No genuine training complaint may trip either WRONG_CUSTOMER trigger."""
    for cid, lab in data.labels().items():
        r = data.complaint(cid)
        text = f"{r.subject} {r.text}"
        assert not extract.third_party_cue(text), cid
        c4 = extract.card_last4(text)
        if c4 and lab.category in ("DUPLICATE_CHARGE", "UNAUTHORISED_CARD", "ATM_NOT_DISPENSED"):
            assert c4 in tools.owned_card_last4(r.customer_id), cid


# --- 2. tool scope ---------------------------------------------------------------------------------------


def _other_customer_atm_txn() -> str:
    return next(t.txn_id for t in data.txns_for("CUS-00002") if t.channel == "ATM Withdrawal")


def test_tools_refuse_other_customers() -> None:
    mine = "CUS-00013"
    assert "error" in tools.call_tool("get_customer", {"customer_id": "CUS-00002"}, mine)
    assert "error" in tools.call_tool("get_accounts", {"customer_id": "CUS-00002"}, mine)
    assert "error" in tools.call_tool(
        "find_transactions",
        {"customer_id": "CUS-00002", "start": "2026-04-01", "end": "2026-09-30", "channels": ["ATM Withdrawal"]},
        mine,
    )
    assert "error" in tools.call_tool("get_atm_journal", {"txn_id": _other_customer_atm_txn()}, mine)
    assert "error" in tools.call_tool("get_reversal", {"txn_id": _other_customer_atm_txn()}, mine)
    assert "error" in tools.call_tool("get_reversal", {"txn_id": "TXN-9999999"}, mine)


def test_tools_serve_own_customer_and_default_the_id() -> None:
    mine = "CUS-00013"
    assert tools.call_tool("get_customer", {"customer_id": mine}, mine)["customer_id"] == mine
    assert tools.call_tool("get_customer", {}, mine)["customer_id"] == mine  # model forgot the id: the case's own
    out = tools.call_tool(
        "find_transactions",
        {"start": "2026-09-01", "end": "2026-09-30", "channels": ["Card e-Commerce"]},
        mine,
    )
    assert out["count"] >= 1
    assert {t["txn_id"] for t in out["transactions"]} <= {t.txn_id for t in data.txns_for(mine)}


def test_bound_handlers_match_tool_specs_and_scope() -> None:
    hs = tools.handlers("CUS-00013")
    assert {s["name"] for s in tools.tool_specs()} == set(hs)
    assert "error" in hs["get_customer"]({"customer_id": "CUS-00002"})
    assert "error" in hs["get_atm_journal"]({"txn_id": _other_customer_atm_txn()})
    own_atm = next((t.txn_id for t in data.txns_for("CUS-02394") if data.atm_journal(t.txn_id)), None)
    assert own_atm is not None
    assert "error" not in tools.handlers("CUS-02394")["get_atm_journal"]({"txn_id": own_atm})


# --- 3. Malay loanwords ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Saya buat transfer RM500 semalam tapi gagal, tolong check dan refund",
        "Saya dicaj dua kali di kedai tadi. Tolong refund.",
        "Saya guna app untuk buat online transfer tapi OTP tak sampai, tolong check card saya",
    ],
)
def test_malay_with_english_loanwords_is_ms(text: str) -> None:
    assert lang.detect(text) == "MS"


def test_genuine_code_switching_stays_mixed() -> None:
    assert lang.detect("I tried to pay at the shop but kad saya declined, tolong bantu bank saya") == "MIXED"
    assert lang.detect("Hi, kenapa ada monthly service charge RM2.00 bulan Ogos? Tolong refund ya.") == "MIXED"


def test_reply_language_ms_loanword_sentence_ignores_preference() -> None:
    row = _row("Saya dicaj dua kali di kedai tadi. Tolong refund.", "CUS-00013")
    assert lang.reply_language(row)[0] == "MS"


# --- 4. below-tau guesses do not auto-refund -------------------------------------------------------------


def _customer_with_single_atm() -> tuple[str, datetime, str]:
    """A customer with exactly one ATM debit in 45 days of some day: (customer, received_at, txn_id)."""
    for c in data.customers():
        atms = [t for t in data.txns_for(c.customer_id) if t.channel == "ATM Withdrawal" and t.direction == "DR"]
        if len(atms) == 1:
            t = atms[0]
            return c.customer_id, datetime(t.txn_time.year, t.txn_time.month, t.txn_time.day, 23, 0), t.txn_id
    raise AssertionError("no customer with a single ATM debit")


def test_low_classifier_confidence_is_ambiguous_with_reason() -> None:
    cust, received, txn_id = _customer_with_single_atm()
    t = data.txn(txn_id)
    text = f"ATM took my money, RM{t.amount} withdrawal"
    row = ComplaintRow(customer_id=cust, received_at=received, channel="App chat", text=text)
    issue = extract.regex_issue(row, "ATM_NOT_DISPENSED")
    window = dates.full_window(row.received_at)

    sure = match.match_case(row, _u(issue, "classifier", 0.99), window, _noop)
    assert (sure.status, sure.txn_id) == ("UNIQUE", txn_id)

    events: list[StageEvent] = []
    low = match.match_case(row, _u(issue, "classifier", classify.tau() - 0.01), window, events.append)
    assert (low.status, low.txn_id) == ("AMBIGUOUS", None)
    assert events[0].payload["reason"] == "low_category_confidence"
    assert events[0].payload["candidates"][0]["txn_id"] == txn_id  # the officer still sees it

    # rules / llm decided: tau does not apply
    assert match.match_case(row, _u(issue, "rules", 0.1), window, _noop).status == "UNIQUE"


def test_low_confidence_investigator_pick_is_still_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    cust, received, txn_id = _customer_with_single_atm()
    t = data.txn(txn_id)
    row = ComplaintRow(customer_id=cust, received_at=received, channel="App chat", text=f"RM{t.amount} atm")
    issue = extract.regex_issue(row, "ATM_NOT_DISPENSED")
    window = dates.full_window(row.received_at)
    monkeypatch.setattr(match, "_investigate", lambda *_a: txn_id)
    m = match.match_case(row, _u(issue, "classifier", 0.1), window, _noop)
    assert (m.status, m.txn_id, m.source) == ("UNIQUE", txn_id, "investigator")


def test_service_quality_ignores_low_confidence() -> None:
    row = _row("The staff were rude")
    m = match.match_case(row, _u(Issue(category="SERVICE_QUALITY"), "classifier", 0.1), dates.full_window(row.received_at), _noop)
    assert m.status == "NO_TXN"


# --- 5. lone survivor needs a discriminating clue --------------------------------------------------------


def test_lone_survivor_without_a_clue_is_not_unique() -> None:
    cust, received, txn_id = _customer_with_single_atm()
    row = ComplaintRow(customer_id=cust, received_at=received, channel="App chat", text="ATM problem")
    window = dates.full_window(row.received_at)
    m = match.match_case(row, _u(Issue(category="ATM_NOT_DISPENSED")), window, _noop)
    assert m.status == "NONE" and m.txn_id is None
    assert [c.txn_id for c in m.candidates] == [txn_id]  # kept for the trace

    clued = Issue(category="ATM_NOT_DISPENSED", amount=data.txn(txn_id).amount)
    assert match.match_case(row, _u(clued), window, _noop).status == "UNIQUE"


def test_date_range_alone_is_not_discriminating() -> None:
    cust, received, txn_id = _customer_with_single_atm()
    row = ComplaintRow(customer_id=cust, received_at=received, channel="App chat", text="ATM problem last week")
    t = data.txn(txn_id)
    d = t.txn_time.date()
    window = DateWindow(start=d, end=d, exact_day=None, phrase="last week")
    m = match.match_case(row, _u(Issue(category="ATM_NOT_DISPENSED")), window, _noop)
    assert m.status == "NONE"
    exact = DateWindow(start=d, end=d, exact_day=d, phrase="on the day")
    assert match.match_case(row, _u(Issue(category="ATM_NOT_DISPENSED")), exact, _noop).status == "UNIQUE"


def test_my_transfer_failed_never_refunds() -> None:
    for cust in ("CUS-00020", "CUS-00013", "CUS-00150"):
        m, _ = _match_text("My transfer failed.", "FAILED_TRANSFER", customer=cust)
        assert m.status in ("NONE", "AMBIGUOUS"), cust
        assert m.txn_id is None


# --- 6. OOF is keyed by id and text ----------------------------------------------------------------------


def test_oof_needs_the_genuine_training_text() -> None:
    genuine = data.complaint("CMP-00165")
    _, held_out = classify.probabilities(genuine)
    assert held_out
    reused = genuine.model_copy(update={"text": "I need to update my address", "subject": ""})
    probs, held_out2 = classify.probabilities(reused)
    assert not held_out2
    cls = classify._artifact().classes
    assert cls[int(probs.argmax())] != "DUPLICATE_CHARGE" or float(probs.max()) < 0.9
    # same id, same text, different customer/time: still the same complaint text -> OOF
    again = genuine.model_copy(update={"customer_id": "CUS-00001"})
    assert classify.probabilities(again)[1]


# --- 7. romance cues -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I love your app but my transfer failed",
        "Love the new design, however I was charged twice",
        "saya suka app ini tetapi caj dua kali",
    ],
)
def test_ordinary_love_is_not_a_scam_cue(text: str) -> None:
    assert not classify.tier0(_row(text)).scam_cue


@pytest.mark.parametrize(
    "text",
    [
        "I met someone on Facebook and we fell in love, then he asked for money",
        "It was a love scam, my online boyfriend asked me to transfer",
        "kekasih online saya minta wang",
        "teman lelaki online saya minta duit",
        "dating app match asked me to pay",
    ],
)
def test_romance_scam_cues_still_fire(text: str) -> None:
    assert classify.tier0(_row(text)).scam_cue


def test_scam_cue_recall_over_train_holds() -> None:
    hit = n = fp = 0
    for cid, lab in data.labels().items():
        cue = classify.tier0(data.complaint(cid)).scam_cue
        if lab.category == "SCAM_TRANSFER":
            n += 1
            hit += cue
        elif cue:
            fp += 1
    assert hit >= 204 and fp == 0, (hit, n, fp)


def test_real_extractor_still_matches_all_train_gold() -> None:
    """The real regex clues (not the test-local stand-in in test_match.py) with the stricter rules: 1750/1750."""
    wrong: list[str] = []
    for cid, lab in data.labels().items():
        row = data.complaint(cid)
        text = f"{row.subject} {row.text}"
        issue = extract.regex_issue(row, lab.category)  # type: ignore[arg-type]
        window = dates.resolve_window(dates.find_date_phrase(text), row.received_at)
        m = match.match_case(row, _u(issue), window, _noop)
        if (m.txn_id or "") != lab.matched_txn_id:
            wrong.append(cid)
    assert wrong == []
