"""C7 self-check (SPEC §4.7 checks 1-5) and the deterministic templates (§4.6), on the real chain for real complaints."""

import importlib.util
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from teratai import check, classify, data, dates, match, policy, reply, templates
from teratai.models import Decision, FactSheet, MatchResult, StageEvent

STARTER = Path(__file__).resolve().parents[3] / "starter"


def _noop(_e: StageEvent) -> None:
    return None


def chain(complaint_id: str) -> tuple[FactSheet, Decision]:
    """Real chain: understand -> resolve -> match -> decide -> build_facts."""
    row = data.complaint(complaint_id)
    u = classify.understand(row, "batch", _noop)
    issue = u.issues[0]
    window = dates.resolve_window(issue.date_phrase, row.received_at)
    m = match.match_case(row, u, window, _noop)
    d = policy.decide(row, issue.category, m)
    return reply.build_facts(row, issue.category, m, d), d


def issue_codes(text: str, facts: FactSheet) -> list[str]:
    return [i.code for i in check.check_reply(text, facts).issues]


@pytest.fixture(scope="module")
def f244() -> FactSheet:
    return chain("CMP-00244")[0]


@pytest.fixture(scope="module")
def starter_check() -> ModuleType:
    sys.path.insert(0, str(STARTER))
    try:
        spec = importlib.util.spec_from_file_location("starter_check_reply", STARTER / "check_reply.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.DB = mod.load()
        return mod
    finally:
        sys.path.remove(str(STARTER))


# --- DEMO §3: CMP-00244 ------------------------------------------------------------------------------


def test_cmp_00244_facts(f244: FactSheet) -> None:
    assert (f244.category, f244.outcome, f244.refund_myr, f244.language) == (
        "ATM_NOT_DISPENSED",
        "REFUND",
        Decimal("550.00"),
        "EN",
    )
    assert f244.ids["txn"] == "TXN-0088211"
    assert f244.amounts["requested"] == Decimal("1500.00") and f244.amounts["dispensed"] == Decimal("950.00")


def test_cmp_00244_template_is_clean_and_passes_starter(f244: FactSheet, starter_check: ModuleType) -> None:
    text = templates.render(f244)
    assert check.check_reply(text, f244).ok
    assert "RM550.00" in text and "TXN-0088211" in text
    assert starter_check.check_reply(starter_check.DB, "CMP-00244", text) == []


@pytest.mark.parametrize(
    "edit, code, token",
    [
        ("RM550.00", "AMOUNT", "RM600.00"),  # DEMO §3.2
        ("RM550.00", "AMOUNT", "RM800.00"),  # in the customer's history, not in this case (§3.4)
        ("TXN-0088211", "TXN_ID", "TXN-0088299"),
    ],
)
def test_cmp_00244_edited_reply_is_flagged(f244: FactSheet, edit: str, code: str, token: str) -> None:
    text = templates.render(f244).replace(edit, token)
    result = check.check_reply(text, f244)
    assert not result.ok
    hit = next(i for i in result.issues if i.code == code)
    assert hit.token == token
    if code == "AMOUNT":
        assert hit.message == f"amount {token} is not in this case's evidence"
    else:
        assert hit.message == f"transaction {token} is not in this case's evidence"


def test_rm800_passes_the_starter_but_not_ours(f244: FactSheet, starter_check: ModuleType) -> None:
    text = "We have refunded RM800.00 for transaction TXN-0088211."
    assert starter_check.check_reply(starter_check.DB, "CMP-00244", text) == []
    assert "AMOUNT" in issue_codes(text, f244)


def test_phone_number_is_flagged(f244: FactSheet) -> None:
    text = templates.render(f244).replace("Yours sincerely", "Call us at 03-1234 5678. Yours sincerely")
    issues = check.check_reply(text, f244).issues
    assert [(i.code, i.token) for i in issues] == [("PHONE_URL", "03-1234 5678")]


# --- per check ---------------------------------------------------------------------------------------


def _decline(facts: FactSheet) -> FactSheet:
    return facts.model_copy(update={"outcome": "DECLINE", "refund_myr": Decimal("0.00")})


def test_refund_verb_on_decline_is_flagged(f244: FactSheet) -> None:
    f = _decline(f244)
    for promise in (
        "We have refunded you.",
        "The amount will be refunded to you.",
        "We will refund RM550.00.",
        "The money was credited back to you.",
        "Wang anda akan dikreditkan semula.",
    ):
        assert "OUTCOME" in issue_codes(f"Dear customer, thank you for your message. {promise}", f), promise


def test_refusal_wording_is_not_a_promise(f244: FactSheet) -> None:
    f = _decline(f244)
    text = (
        "Dear customer, thank you for contacting us. We are unable to refund this, and we cannot refund it."
    )
    assert "OUTCOME" not in issue_codes(text, f)
    assert "OUTCOME" not in issue_codes(
        "Dear customer, no refund is due for this transaction on your account.", f
    )


def test_refund_outcome_needs_the_refund_amount(f244: FactSheet) -> None:
    text = (
        "Dear Ms Aisyah, thank you for contacting us. We will refund the shortfall to your account in 7 days."
    )
    result = check.check_reply(text, f244)
    assert [i.code for i in result.issues] == ["OUTCOME"]
    assert "RM550.00" in result.issues[0].message


def test_amount_forms(f244: FactSheet) -> None:
    ok = "Dear Ms Aisyah, you requested RM 1,500.00, got MYR 950, and we will refund 550 ringgit (RM550.00)."
    assert check.check_reply(ok, f244).ok
    for bad in ("RM1,501.00", "MYR 951.00", "RM 99", "rm600", "650 ringgit"):
        text = f"Dear Ms Aisyah, thank you for writing to us. We will refund RM550.00. Also {bad}."
        assert "AMOUNT" in issue_codes(text, f244), bad


def test_auto_refund_limit_is_allowed(f244: FactSheet) -> None:
    text = "Dear Ms Aisyah, refunds above RM500.00 need approval. We will refund RM550.00 to your account."
    assert check.check_reply(text, f244).ok


def test_wrong_language_is_flagged(f244: FactSheet) -> None:
    ms = "Tuan, terima kasih kerana menghubungi pihak bank. Jumlah RM550.00 akan dikreditkan semula ke akaun anda."
    assert "LANGUAGE" in issue_codes(ms, f244)
    en_facts = f244.model_copy(update={"language": "MS"})
    assert "LANGUAGE" in issue_codes(templates.render(f244), en_facts)


def test_mixed_reply_passes_only_when_the_reply_language_dominates(f244: FactSheet) -> None:
    mostly_en = (
        "Dear Ms Aisyah, thank you for contacting us. We will refund RM550.00 to your account, "
        "and we will tell you when this is done. Sekian, terima kasih."
    )
    assert check.check_reply(mostly_en, f244).ok
    assert "LANGUAGE" in issue_codes(mostly_en, f244.model_copy(update={"language": "MS"}))


def test_urls_and_unverified_numbers(f244: FactSheet) -> None:
    base = "Dear Ms Aisyah, thank you for writing to us. We will refund RM550.00 to your account. "
    for extra in (
        "Visit https://evil.example.com/pay",
        "See www.teratai-help.com",
        "Email help@teratai.com.my",
        "Call 999 now",
        "Hubungi talian 1300 22 3344",
        "WhatsApp +60 12-345 6789",
    ):
        assert "PHONE_URL" in issue_codes(base + extra, f244), extra
    for extra in (
        "Call the National Scam Response Centre at 997.",
        "Contact BNMLINK at 1-300-88-5465.",
        "See https://www.fmos.org.my/en/faq/",
        "We will reply within 7 working days on 2026-07-20 or 20/07/2026.",
    ):
        assert check.check_reply(base + extra, f244).ok, extra


def test_hygiene(f244: FactSheet) -> None:
    base = "Dear Ms Aisyah, we will refund RM550.00 to your account. "
    for extra in (
        "Route: AUTO_RESOLVE",
        "Category ATM_NOT_DISPENSED",
        "Rule ATM_NOT_DISPENSED.REFUND",
        "Priority P1",
        "{name}",
    ):
        assert "HYGIENE" in issue_codes(base + extra, f244), extra
    assert "HYGIENE" in issue_codes(base + "More detail. " * 100, f244)


def test_token_verdicts_give_positions_for_highlighting(f244: FactSheet) -> None:
    text = "Dear Ms A, TXN-0088211 and TXN-0088299 for RM550.00 / RM600.00 call 997 or 03-1234 5678."
    got = [(v.kind, v.text, v.verified) for v in check.token_verdicts(text, f244)]
    assert got == [
        ("TXN_ID", "TXN-0088211", True),
        ("TXN_ID", "TXN-0088299", False),
        ("AMOUNT", "RM550.00", True),
        ("AMOUNT", "RM600.00", False),
        ("PHONE_URL", "997", True),
        ("PHONE_URL", "03-1234 5678", False),
    ]
    assert all(text[v.start : v.end] == v.text for v in check.token_verdicts(text, f244))


def test_only_this_cases_facts_are_allowed(f244: FactSheet) -> None:
    other = f244.model_copy(update={"ids": {"state": "decided", "txn": "TXN-0088299"}})
    assert "TXN_ID" in issue_codes("Dear Ms Aisyah, see TXN-0088211. We will refund RM550.00.", other)


# --- regression IDs from the real chain ----------------------------------------------------------------


def test_cmp_00165_duplicate_refund_in_malay() -> None:
    f, d = chain("CMP-00165")
    text = templates.render(f)
    assert (f.language, d.outcome, f.refund_myr) == ("MS", "REFUND", Decimal("46.66"))
    assert "TXN-0115572" in text and "RM46.66" in text and "Sekian, terima kasih" in text
    assert check.check_reply(text, f).ok
    assert "AMOUNT" in issue_codes(text.replace("RM46.66", "RM47.66"), f)


def test_cmp_00387_investigate_is_a_holding_reply() -> None:
    f, d = chain("CMP-00387")
    text = templates.render(f)
    assert d.outcome == "INVESTIGATE" and f.refund_myr == 0
    assert check.check_reply(text, f).ok
    assert "refund" not in text.lower().replace("no decision on a refund", "")
    assert "OUTCOME" in issue_codes(text + " We have refunded you.", f)


def test_cmp_00289_large_refund_keeps_its_amount() -> None:
    f, _ = chain("CMP-00289")
    text = templates.render(f)
    assert f.refund_myr == Decimal("4687.10") and "RM4,687.10" in text
    assert check.check_reply(text, f).ok


def test_decline_templates_carry_redress_and_no_promise() -> None:
    cid = next(c for c, lab in data.labels().items() if lab.outcome == "DECLINE")
    f, d = chain(cid)
    text = templates.render(f)
    assert d.outcome == "DECLINE" and "FMOS" in text and "BNMLINK" in text
    assert check.check_reply(text, f).ok
    assert "OUTCOME" in issue_codes(text + " We have refunded you.", f)


# --- every template passes -------------------------------------------------------------------------------

_ALL_FACTS = {
    "customer_name": "Test Customer",
    "refund_myr": Decimal("12.34"),
    "ids": {
        "state": "decided",
        "txn": "TXN-0000001",
        "merchant": "ShopLah",
        "sibling": "TXN-0000002",
        "reversal": "TXN-0000003",
    },
    "amounts": {
        "txn": Decimal("12.34"),
        "sibling": Decimal("12.34"),
        "reversal": Decimal("12.34"),
        "requested": Decimal("100.00"),
        "dispensed": Decimal("50.00"),
        "shortfall": Decimal("50.00"),
        "charged": Decimal("12.00"),
        "due": Decimal("0.00"),
        "difference": Decimal("12.00"),
    },
    "dates": {"txn": date(2026, 3, 5), "sibling": date(2026, 3, 5), "reversal": date(2026, 3, 6)},
    "sla_days": 7,
}


@pytest.mark.parametrize("language", ["EN", "MS"])
@pytest.mark.parametrize("key", sorted(templates.en.TEXTS))
def test_every_template_key_renders_and_passes(key: str, language: str) -> None:
    assert set(templates.en.TEXTS) == set(templates.ms.TEXTS)
    category, _, rest = key.partition(".")
    kw = dict(_ALL_FACTS)
    state = "decided"
    if key in ("NEEDS_INFO", "NEEDS_INFO.SCAM", "NOT_COMPLAINT", "GENERIC"):
        category, outcome = ("SCAM_TRANSFER" if key == "NEEDS_INFO.SCAM" else "SERVICE_QUALITY"), "DECLINE"
        state = {
            "NEEDS_INFO": "needs_info",
            "NEEDS_INFO.SCAM": "needs_info",
            "NOT_COMPLAINT": "not_complaint",
        }.get(key, "decided")
    else:
        outcome = rest.split(".")[0]
    if key == "FEE_DISPUTE.REFUND":  # a fee with something due (the shared fixture models the waived case)
        kw["amounts"] = {**_ALL_FACTS["amounts"], "due": Decimal("5.00"), "difference": Decimal("7.00")}
        kw["refund_myr"] = Decimal("7.00")
    ids = dict(_ALL_FACTS["ids"])  # type: ignore[arg-type]
    ids["state"] = state
    if state != "decided":
        kw["refund_myr"] = Decimal("0.00")
    f = FactSheet.model_validate(
        {
            **kw,
            "ids": ids,
            "language": language,
            "honorific": "Ms" if language == "EN" else "Puan",
            "category": category,
            "outcome": outcome,
        }
    )
    text = templates.render_key(f, key)
    assert "{" not in text
    result = check.check_reply(text, f)
    assert result.ok, (key, language, result.issues, text)
    assert len(text.split()) <= 120
    assert not re.search(r"RM[\d,]+(?:\.\d{1,2})?,", text), (
        "an amount followed by a comma breaks the starter's float parse"
    )


def test_wrong_customer_gets_no_reply() -> None:
    f = FactSheet.model_validate(
        {
            **_ALL_FACTS,
            "ids": {"state": "wrong_customer"},
            "amounts": {},
            "dates": {},
            "language": "EN",
            "honorific": "Mr",
            "category": "UNAUTHORISED_CARD",
            "outcome": "INVESTIGATE",
            "refund_myr": Decimal("0.00"),
        }
    )
    assert templates.render(f) == ""
    r = reply.write_reply(f, "batch", _noop)
    assert r.text == "" and r.check.ok


def test_missing_fact_falls_back_to_the_generic_reply() -> None:
    f = FactSheet.model_validate(
        {
            **_ALL_FACTS,
            "ids": {"state": "decided"},
            "amounts": {},
            "dates": {},
            "language": "EN",
            "honorific": "",
            "category": "DUPLICATE_CHARGE",
            "outcome": "REFUND",
        }
    )
    text = templates.render(f)
    assert "Dear Test Customer," in text and "being reviewed" not in text and "reviewing it" in text
    assert check.check_reply(text, f.model_copy(update={"outcome": "DECLINE"})).ok


# --- build_facts / write_reply ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, language, want",
    [
        ("Nur Izzati binti Jamal", "MS", "Puan"),
        ("Hafiz bin Ahmad", "MS", "Tuan"),
        ("Kumar a/l Raju", "EN", "Mr"),
        ("Devi a/p Raju", "EN", "Ms"),
        ("Chan Zhi Hao", "MS", "Tuan/Puan"),
        ("Chan Zhi Hao", "EN", ""),
    ],
)
def test_honorific(name: str, language: str, want: str) -> None:
    assert reply.honorific(name, language) == want


def test_needs_info_state_reaches_the_template() -> None:
    row = data.complaint("CMP-00244")
    m = MatchResult.model_validate(
        {
            "status": "AMBIGUOUS",
            "txn_id": None,
            "window": {"start": date(2026, 7, 1), "end": date(2026, 7, 20)},
            "candidates": [],
            "related": {},
            "source": "matcher",
        }
    )
    d = policy.decide(row, "ATM_NOT_DISPENSED", m)
    f = reply.build_facts(row, "ATM_NOT_DISPENSED", m, d)
    assert f.ids == {"state": "needs_info"} and d.needs_info
    r = reply.write_reply(f, "batch", _noop)
    assert "the date of the transaction" in r.text and r.check.ok and "TXN-" not in r.text
    wrong = reply.build_facts(row, "UNAUTHORISED_CARD", m.model_copy(update={"status": "WRONG_CUSTOMER"}), d)
    assert wrong.ids["state"] == "wrong_customer"


def test_write_reply_emits_a_reply_stage_event(f244: FactSheet) -> None:
    events: list[StageEvent] = []
    r = reply.write_reply(f244, "batch", events.append)
    assert r.source == "template" and r.drafts == [r.text] and r.check.ok
    assert [(e.stage, e.ok) for e in events] == [("reply", True)]
    assert events[0].payload["check_ok"] is True


def test_every_train_complaint_gets_a_reply_that_passes_ours_and_the_starter(
    starter_check: ModuleType,
) -> None:
    failures: list[str] = []
    for cid in data.labels():
        f, _ = chain(cid)
        r = reply.write_reply(f, "batch", _noop)
        if not r.check.ok or not r.text:
            failures.append(f"{cid}: {[i.message for i in r.check.issues]}")
        elif problems := starter_check.check_reply(starter_check.DB, cid, r.text):
            failures.append(f"{cid} (starter): {problems}")
    assert failures == [], failures[:5]
