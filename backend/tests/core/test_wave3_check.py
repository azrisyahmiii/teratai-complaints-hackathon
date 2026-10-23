"""Wave-3 review fixes for the self-check (C7): negation, refund verbs, amount / id / URL formats, trivial replies, templates."""

from datetime import date
from decimal import Decimal

import pytest

from teratai import check, templates
from teratai.models import FactSheet
from tests.core.test_check import _ALL_FACTS, _decline, chain, issue_codes

PAD = "Dear Ms Aisyah, thank you for contacting Teratai Bank about this transaction on your account. "


@pytest.fixture(scope="module")
def f244() -> FactSheet:
    return chain("CMP-00244")[0]


def _promise_codes(facts: FactSheet, tail: str) -> list[str]:
    return issue_codes(PAD + tail, _decline(facts))


# --- 1 + 2: negation and refund verbs --------------------------------------------------------------------


@pytest.mark.parametrize(
    "tail",
    [
        "We are unable to refund it. We will refund you.",
        "We cannot waive the fee. We will refund you.",
        "There is no charge. We have refunded it.",
        "We cannot do that. However, we will refund you soon.",
        "Kami tidak dapat membantu. Kami akan membayar balik wang anda.",
    ],
)
def test_negation_does_not_cross_sentences(f244: FactSheet, tail: str) -> None:
    assert "OUTCOME" in _promise_codes(f244, tail), tail


@pytest.mark.parametrize(
    "tail",
    [
        "We have not refunded this charge and it has not been refunded.",
        "The amount will not be refunded.",
        "We are unable to pay you back.",
        "Kami tidak dapat memulangkan wang tersebut.",
        "Wang itu tidak akan dikembalikan.",
    ],
)
def test_direct_negation_is_a_refusal(f244: FactSheet, tail: str) -> None:
    assert "OUTCOME" not in _promise_codes(f244, tail), tail


@pytest.mark.parametrize(
    "promise",
    [
        "Kami akan membayar balik wang anda.",
        "Kami akan bayar balik jumlah itu.",
        "Kami akan memulangkan wang anda.",
        "Wang anda akan dipulangkan.",
        "Kami akan mengkreditkan akaun anda.",
        "Jumlah itu dikreditkan semula.",
        "We have credited your account.",
        "We will pay you back.",
        "A refund will be issued to you.",
        "Your refund has been approved.",
        "We will return your money.",
        "You will be reimbursed.",
        "We have reimbursed you.",
        "We will issue a refund shortly.",
    ],
)
def test_more_refund_verbs_are_flagged_on_a_decline(f244: FactSheet, promise: str) -> None:
    assert "OUTCOME" in _promise_codes(f244, promise), promise


def test_factual_reversal_wording_passes_on_a_decline() -> None:
    f = FactSheet.model_validate(
        {
            **_ALL_FACTS,
            "ids": {"state": "decided", "txn": "TXN-0000001", "reversal": "TXN-0000003"},
            "amounts": {"txn": Decimal("12.34"), "reversal": Decimal("12.34")},
            "dates": {"txn": date(2026, 3, 5), "reversal": date(2026, 3, 6)},
            "language": "EN",
            "honorific": "Ms",
            "category": "FAILED_TRANSFER",
            "outcome": "DECLINE",
            "refund_myr": Decimal("0.00"),
        }
    )
    ok = "The RM12.34 was already credited back to your account on 6 March 2026 (reversal TXN-0000003)."
    assert "OUTCOME" not in issue_codes(PAD + ok, f)
    assert "OUTCOME" in issue_codes(PAD + "The RM12.34 will be credited back to your account.", f)
    assert "OUTCOME" in issue_codes(
        PAD + "The RM12.34 was credited back to your account.", f
    )  # no reversal cited
    ms = f.model_copy(update={"language": "MS"})
    ms_text = (
        "Puan Aisyah, terima kasih kerana menghubungi pihak bank. Wang sebanyak RM12.34 telah dikembalikan "
        "pada 6 Mac 2026 melalui pembalikan TXN-0000003. Tiada bayaran lanjut perlu dibuat."
    )
    assert "OUTCOME" not in issue_codes(ms_text, ms)


# --- 3: amount and id formats -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "RM  600",
        "RM:600",
        "RM-600",
        "600 MYR",
        "600 RM",
        "ringgit 600",
        "RM550.00-600.00",
        "RM550-600",
        "RM550.00 to RM600.00",
        "RM 0.6k",
    ],
)
def test_amount_format_bypasses_are_flagged(f244: FactSheet, bad: str) -> None:
    text = f"{PAD}We will refund RM550.00. Also {bad}."
    assert "AMOUNT" in issue_codes(text, f244), bad


@pytest.mark.parametrize(
    "good", ["RM 550", "RM1500", "RM 1,500.00", "RM 0.5k", "550 ringgit", "RM550.00-RM550"]
)
def test_amount_formats_that_are_in_evidence_pass(f244: FactSheet, good: str) -> None:
    text = f"{PAD}We will refund RM550.00. Also {good}."
    got = [i for i in check.check_reply(text, f244).issues if i.code == "AMOUNT"]
    assert got == [], (good, got)


def test_non_money_numbers_are_not_amounts(f244: FactSheet) -> None:
    text = (
        f"{PAD}We will refund RM550.00 in 7 working days. Call 997 about TXN-0088211 on 20 July 2026 or "
        "2026-07-20, case 12345, and see 1.5 pages. Up to 5 - 7 days."
    )
    assert check.check_reply(text, f244).ok


@pytest.mark.parametrize("bad", ["TXN0088299", "TXN-88299", "TXN-008821", "txn-0088299", "TXN 0088299"])
def test_txn_id_format_bypasses_are_flagged(f244: FactSheet, bad: str) -> None:
    text = f"{PAD}We will refund RM550.00 for {bad}."
    verdicts = [v for v in check.token_verdicts(text, f244) if v.text == bad]
    assert [(v.kind, v.verified) for v in verdicts] == [("TXN_ID", False)], bad
    assert "TXN_ID" in issue_codes(text, f244)


def test_txn_id_case_is_normalised_for_the_right_id(f244: FactSheet) -> None:
    assert check.check_reply(f"{PAD}We will refund RM550.00 for txn-0088211.", f244).ok


# --- 4: empty / trivial replies -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["", "Ok.", "...", "Thank you for your message.", "Dear Ms Aisyah, we will refund RM550.00."]
)
def test_empty_or_trivial_reply_fails(f244: FactSheet, text: str) -> None:
    result = check.check_reply(text, f244)
    assert not result.ok and "HYGIENE" in [i.code for i in result.issues], text


def test_empty_reply_fails_even_for_wrong_customer() -> None:
    f = FactSheet.model_validate(
        {
            **_ALL_FACTS,
            "ids": {"state": "wrong_customer"},
            "amounts": {},
            "dates": {},
            "language": "EN",
            "honorific": "",
            "category": "UNAUTHORISED_CARD",
            "outcome": "INVESTIGATE",
            "refund_myr": Decimal("0.00"),
        }
    )
    assert not check.check_reply("", f).ok


# --- 6: URLs and emails ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        "bit.ly/x",
        "goo.gl/abc",
        "t.me/scam",
        "wa.me/60123",
        "evil.xyz/pay",
        "teratai.bank/help",
        "teratai.bank",
        "http://evil.example.com/pay",
        "https://fmos.org.my.evil.com/x",
        "www.teratai-help.com",
        "help@teratai.com.my",
        "help@fmos.org.my",
        "user@evil.tk",
    ],
)
def test_any_url_or_email_is_flagged(f244: FactSheet, link: str) -> None:
    text = f"{PAD}We will refund RM550.00. Please visit {link} today."
    assert "PHONE_URL" in issue_codes(text, f244), link


@pytest.mark.parametrize(
    "extra",
    [
        "Please see https://www.fmos.org.my/en/faq/ today.",
        "Please visit www.bnm.gov.my/bnmlink for help.",
        "It cost 1.50 for TXN-0088211.We will explain.",
        "We checked your account.We found no error.",
        "That is, e.g. a fee, i.e. a charge, at 9 a.m. today.",
    ],
)
def test_no_false_url_flags(f244: FactSheet, extra: str) -> None:
    text = f"{PAD}We will refund RM550.00 to you. {extra}"
    got = [i for i in check.check_reply(text, f244).issues if i.code in ("PHONE_URL", "AMOUNT", "TXN_ID")]
    assert got == [], (extra, got)


def test_rm_decimal_is_not_a_url(f244: FactSheet) -> None:
    text = f"{PAD}We will refund RM550.00. The fee was RM1.50.We checked it."
    assert [i.code for i in check.check_reply(text, f244).issues] == ["AMOUNT"]


# --- 8: templates -------------------------------------------------------------------------------------------


def test_scam_and_investigate_templates_state_the_ten_day_update() -> None:
    f, _ = chain("CMP-00387")
    assert "at least every 10 working days" in templates.render(f)
    scam = FactSheet.model_validate(
        {
            **_ALL_FACTS,
            "ids": {"state": "decided", "txn": "TXN-0000001", "merchant": "X"},
            "amounts": {"txn": Decimal("12.34")},
            "dates": {"txn": date(2026, 3, 5)},
            "language": "EN",
            "honorific": "Ms",
            "category": "SCAM_TRANSFER",
            "outcome": "INVESTIGATE",
            "refund_myr": Decimal("0.00"),
        }
    )
    for lg, phrase in (
        ("EN", "at least every 10 working days"),
        ("MS", "sekurang-kurangnya setiap 10 hari bekerja"),
    ):
        facts = scam.model_copy(update={"language": lg})
        text = templates.render(facts)
        assert phrase in text and len(text.split()) <= 120, (lg, text)
        assert check.check_reply(text, facts).ok


def test_malay_templates_do_not_use_bad_news_wording_for_apologies() -> None:
    for key, text in templates.ms.TEXTS.items():
        assert "terkesan" not in text and "Dukacita" not in text, key
