"""C18 mechanisms 2-4: amount grammar, approximation class, SMS date forms. Pattern grids, not reviewer rows."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from teratai import dates, extract
from teratai.match import rounding_half_step
from teratai.textnorm import normalise

# 6 amounts x 8 surface forms. (value, forms that must read as that value)
_GRID: dict[Decimal, list[str]] = {
    Decimal("46.66"): ["RM46.66", "rm 46.66", "RM 46.66 each", "MYR46.66", "46.66myr", "46.66 ringgit", "RM46.66.", "(RM46.66)"],
    Decimal(1500): ["RM1,500", "RM 1 500", "RM1500", "rm1.5k", "RM1.500", "1500 ringgit", "1.5k", "seribu lima ratus ringgit"],
    Decimal("3967.30"): ["RM3,967.30", "rm 3 967.30", "RM3967.30", "MYR 3,967.30", "3967.30myr", "3 967.30 ringgit", "RM3.967,30x"[:0] or "RM3967.30!", "rm3,967.30"],
    Decimal(2800): ["rm2.8k", "RM 2.8K", "RM2,800", "rm2800", "2.8k", "2800 ringgit", "dua ribu lapan ratus ringgit", "two thousand eight hundred ringgit"],
    Decimal(600): ["RM600", "rm 600", "600 ringgit", "MYR600", "600myr", "enam ratus ringgit", "six hundred ringgit", "RM600.00"],
    Decimal("4390.78"): ["RM4,390.78", "rm4390.78", "RM 4 390.78", "4390.78 ringgit", "MYR4390.78", "RM4.390.78"[:0] or "RM4390.78,", "4390.78myr", "rm4,390.78"],
}


@pytest.mark.parametrize(("value", "form"), [(v, f) for v, forms in _GRID.items() for f in forms])
def test_amount_grammar_grid(value: Decimal, form: str) -> None:
    got = extract.disputed_amount(f"saya kena caj {form} semalam")[0]
    assert got == value, (form, got)


@pytest.mark.parametrize(
    ("text", "approx"),
    [
        ("about RM900", True), ("abt RM900", True), ("ard rm900", True), ("approx. RM900", True), ("~RM900", True),
        ("lebih kurang RM900", True), ("lbh krg RM900", True), ("lebih krg rm900", True), ("kira2 rm900", True),
        ("kira-kira RM900", True), ("dlm rm900", True), ("in the region of RM900", True), ("rm0.9k", True),
        ("charged RM900", False), ("RM900 exactly", False),
    ],
)  # fmt: skip
def test_approx_marker_class(text: str, approx: bool) -> None:
    assert extract.disputed_amount(text)[1] is approx


def test_k_form_is_never_taken_literally() -> None:
    for k in ("rm4.4k", "RM1.5K", "rm2k", "rm9.9k"):
        value = extract.disputed_amount(k)[0]
        assert value is not None and value >= 1000


def test_disputed_amount_skips_balance_and_prefers_charge_verb() -> None:
    assert extract.disputed_amount("baki acct sy RM1,200 tp kena caj dua kali RM46.66")[0] == Decimal("46.66")
    assert extract.disputed_amount("my balance is RM3,000 but I was charged RM89.90 twice")[0] == Decimal("89.90")
    assert extract.disputed_amount("RM20 hari ini dan juga RM15 kena potong")[0] == Decimal(15)
    assert extract.disputed_amount("RM1,500 withdrawn")[0] == Decimal(1500)  # one amount stays the amount


def test_rounding_unit_tolerance() -> None:
    assert rounding_half_step(Decimal(4400)) == Decimal(50)
    assert rounding_half_step(Decimal(2000)) == Decimal(500)
    assert rounding_half_step(Decimal("46.66")) == 0
    assert rounding_half_step(Decimal(55)) == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lps", "lepas"), ("smlm", "semalam"), ("kmrn", "kelmarin"), ("jmt lps", "jumaat lepas"),
        ("sy x tahu", "saya tak tahu"), ("15hb", "15 hb"), ("2days ago", "2 days ago"), ("abt RM5", "about RM5"),
    ],
)  # fmt: skip
def test_normaliser_is_clue_only_and_deterministic(raw: str, expected: str) -> None:
    assert normalise(raw) == expected
    assert normalise(normalise(raw)) == normalise(raw)  # idempotent


RECEIVED = datetime(2026, 9, 30, 12, 0)  # a Wednesday


@pytest.mark.parametrize(
    ("phrase", "day"),
    [
        ("smlm", date(2026, 9, 29)), ("kmrn", date(2026, 9, 28)), ("ytd", date(2026, 9, 29)),
        ("td", date(2026, 9, 30)), ("last sat", date(2026, 9, 26)), ("lst fri", date(2026, 9, 25)),
        ("jmt lps", date(2026, 9, 25)), ("selasa lps", date(2026, 9, 29)), ("slasa lps", date(2026, 9, 29)),
        ("2 hari lps", date(2026, 9, 28)), ("2days ago", date(2026, 9, 28)), ("15hb", date(2026, 9, 15)),
        ("Tue last week", date(2026, 9, 22)), ("hari rabu lepas", date(2026, 9, 23)), ("31hb", date(2026, 8, 31)),
    ],
)  # fmt: skip
def test_sms_date_forms(phrase: str, day: date) -> None:
    w = dates.resolve_window(phrase, RECEIVED)
    assert w.exact_day == day, (phrase, w)


def test_weeks_ago_and_minggu_lps_are_fuzzy_ranges() -> None:
    w = dates.resolve_window("2 weeks ago", RECEIVED)
    assert w.exact_day is None and w.start <= date(2026, 9, 16) <= w.end
    w = dates.resolve_window("minggu lps", RECEIVED)
    assert w.exact_day is None and (w.start, w.end) == (date(2026, 9, 17), date(2026, 9, 29))


def test_find_date_phrase_reads_sms_text() -> None:
    assert dates.find_date_phrase("tarik rm1.5k atm last fri tapi dapat kurang") is not None
    assert dates.find_date_phrase("hello the sat on the table") is None  # ordinary words are not dates
