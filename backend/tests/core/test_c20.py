"""C20 harness-evaluation fixes (docs/dev/reviews/2026-10-23-harness-evaluation.md §9)."""

from datetime import date
from pathlib import Path

import pytest

from teratai import evaluate, extract, investigate
from teratai.models import ComplaintRow, DateWindow, Issue, StageEvent
from teratai.pipeline import process_complaint

PAN_ROW = ComplaintRow(
    complaint_id="E10",
    customer_id="CUS-01363",
    received_at="2026-09-20 13:22",  # type: ignore[arg-type]
    channel="Email",
    subject="",
    text="Unauthorised RM151.88 LUXEGOODS LONDON last fri. My IC 740529-10-5531, full card no 4111 1111 1111 3691. "
    "Refund pls",
)


# --- §9 #3: a full card number gives its last four, never its issuer prefix --------------------------------
@pytest.mark.parametrize(
    "text, last4",
    [
        ("full card no 4111 1111 1111 3691. Refund pls", "3691"),
        ("kad saya 4111-1111-1111-3691 dicaj", "3691"),
        ("card number 4111111111113691 was charged", "3691"),
        ("Visa 4111 1111 1111 3 was charged", "1113"),  # 13-digit PAN: still its last four
        ("someone used 4111 1111 1111 3691 at Lazada", "3691"),  # 4-4-4-4 with no card word
        ("transferred to account 1234 5678 9012 3456", None),  # a recipient's account, not the customer's card
        ("charge RM10 (card ending 2832)", "2832"),  # unchanged
        ("card ending 2832, called 03-1234 5678", "2832"),  # a phone number is not a PAN
        ("my card ending 2832.", "2832"),  # sentence end (was None: "." was taken for a decimal point)
        ("kad berakhir 2832, tolong semak", "2832"),
        ("card 1234.50 charged", None),  # money, not a card
    ],
)
def test_card_last4_reads_the_end_of_a_full_card_number(text: str, last4: str | None) -> None:
    assert extract.card_last4(text) == last4


def test_mask_sensitive_keeps_only_the_last_four_digits() -> None:
    assert extract.mask_sensitive("card 4111 1111 1111 3691.") == "card **** **** **** 3691."
    assert extract.mask_sensitive("no 4111111111113691") == "no ************3691"
    assert extract.mask_sensitive("My IC 740529-10-5531,") == "My IC ******-**-5531,"
    unchanged = "RM1,500.00 on 2026-09-19 10:15, TXN-0088211, call 03-1234 5678, card ending 2832"
    assert extract.mask_sensitive(unchanged) == unchanged


def test_no_card_or_ic_number_reaches_the_llm() -> None:
    window = DateWindow(start=date(2026, 9, 1), end=date(2026, 9, 20))
    for msg in (
        extract._user_message(PAN_ROW),
        investigate.build_user_message(PAN_ROW, Issue(category="UNAUTHORISED_CARD"), window, []),
    ):
        assert "4111" not in msg and "740529" not in msg
        assert "**** **** **** 3691" in msg and "******-**-5531" in msg


def test_full_card_number_complaint_is_not_wrong_customer() -> None:
    # The review's curveball: "4111" was read as the last four -> WRONG_CUSTOMER and the valid refund was lost.
    # (Offline the investigator can't settle this low-confidence row, so the refund itself is checked live.)
    events: list[StageEvent] = []
    process_complaint(PAN_ROW, "eval", events.append)
    clues = next(e.payload["clues"] for e in events if e.stage == "understand")
    assert clues["card_last4"] == "3691"
    assert all((e.payload or {}).get("status") != "WRONG_CUSTOMER" for e in events if e.stage == "match")


# --- §9 #7: the outage path (LLM unreachable / replay cache empty) was never exercised by an eval -----------------
def test_llm_outage_every_messy_row_gets_a_checked_template_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DEMO_MODE=cached with an empty cache = every LLM call misses: extract, investigator and reply all degrade.
    monkeypatch.setenv("DEMO_MODE", "cached")
    monkeypatch.setenv("LLM_CACHE_PATH", str(tmp_path / "empty.sqlite"))
    monkeypatch.setenv("EXTRACT_MODE", "llm")
    monkeypatch.setenv("REPLY_MODE", "llm")
    monkeypatch.setenv("INVESTIGATOR", "on")
    rows = evaluate.load_rows(Path(__file__).parent / "fixtures" / "messy_dev.csv")
    for r in rows:
        events: list[StageEvent] = []
        d = process_complaint(r, "live", events.append)
        reply = [e for e in events if e.stage == "reply"][-1].payload
        assert reply["source"] == "template" and d.check_ok, r.complaint_id
        assert d.to_csv_row()["reply_text"].strip() or "wrong_customer" in d.flags, r.complaint_id
        assert any((e.payload or {}).get("degraded") for e in events), r.complaint_id


# --- §9 #4: Malay "pasukan penipuan" reads as "our scam team" -----------------------------------------------------
def test_malay_replies_never_call_the_fraud_team_a_scam_team() -> None:
    from teratai import reply
    from teratai.templates import ms

    for key, text in ms.TEXTS.items():
        assert "pasukan penipuan" not in text.lower(), key
    assert "pasukan siasatan penipuan" in ms.TEXTS["SCAM_TRANSFER.INVESTIGATE"].lower()
    assert "pasukan siasatan penipuan" in ms.TEXTS["UNAUTHORISED_CARD.INVESTIGATE"].lower()
    assert 'never "pasukan penipuan"' in reply.SYSTEM_PROMPT and reply.PROMPT_VERSION == "reply-v2"


# --- §9 #6: FMOS excludes fees & charges disputes (fmos.org.my FAQ Q9), so a fee decline offers BNMLINK only ---------
def _first(category: str, outcome: str, language: str) -> str:
    from teratai import data

    return next(
        lb.complaint_id
        for lb in data.labels().values()
        if (lb.category, lb.outcome, lb.reply_language) == (category, outcome, language)
    )


@pytest.mark.parametrize("language", ["EN", "MS"])
def test_fee_decline_offers_bnmlink_not_fmos(language: str) -> None:
    from teratai import data, reply
    from teratai.templates import render

    d = process_complaint(data.complaint(_first("FEE_DISPUTE", "DECLINE", language)), "eval")
    assert d.outcome == "DECLINE" and d.facts.language == language
    for text in (render(d.facts), reply.fact_sheet_text(d.facts)):
        assert "BNMLINK" in text and "1-300-88-5465" in text
        assert "FMOS" not in text and "Ombudsman" not in text
    assert d.check_ok


def test_other_declines_still_offer_fmos() -> None:
    from teratai import data
    from teratai.templates import render

    d = process_complaint(data.complaint(_first("ATM_NOT_DISPENSED", "DECLINE", "EN")), "eval")
    assert "FMOS" in render(d.facts) and "BNMLINK" in render(d.facts)


# --- §9 #8: a negated Malay refund is a refusal, not a promise (1 false positive in 284 replies) ------------------
@pytest.mark.parametrize(
    "sentence, flagged",
    [
        ("Oleh itu, pihak bank tidak akan membuat bayaran balik baharu.", False),
        ("Pihak bank tidak akan membuat sebarang bayaran balik.", False),
        ("Kami tidak dapat memberikan bayaran balik.", False),
        ("Pihak bank akan membuat bayaran balik kepada anda.", True),
        ("Kami tidak sabar untuk membuat bayaran balik kepada anda.", True),  # "can't wait to refund": a promise
        ("We cannot confirm the date, but we will refund you.", True),
    ],
)
def test_negated_malay_refund_is_not_a_promise(sentence: str, flagged: bool) -> None:
    from teratai import check, data

    facts = process_complaint(data.complaint(_first("FAILED_TRANSFER", "DECLINE", "MS")), "eval").facts
    assert facts.outcome == "DECLINE"
    issues = check.check_reply(sentence, facts).issues
    assert any(i.code == "OUTCOME" for i in issues) is flagged
