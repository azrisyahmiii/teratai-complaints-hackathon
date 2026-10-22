"""Date resolver tests (SPEC §4.3): phrases mined from data/complaints.csv plus DEMO.md cases."""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from teratai.dates import MATCH_WINDOW_DAYS, find_date_phrase, resolve_window

DATA = Path(__file__).resolve().parents[3] / "data"


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _d(s: str) -> date:
    return date.fromisoformat(s)


# (phrase, received_at, start, end, exact_day). exact_day None = fuzzy range.
EXACT_CASES = [
    # DEMO.md regressions
    ("hari Selasa lepas", "2026-08-24 09:25", "2026-08-17", "2026-08-19", "2026-08-18"),  # CMP-00165, Mon
    ("last Friday", "2026-07-20 22:32", "2026-07-16", "2026-07-18", "2026-07-17"),  # CMP-00244, Mon
    ("last Saturday", "2026-09-23 21:55", "2026-09-18", "2026-09-20", "2026-09-19"),  # CMP-00387, Wed
    ("last Friday", "2026-09-02 16:43", "2026-08-27", "2026-08-29", "2026-08-28"),  # CMP-00289, Wed
    ("today", "2026-09-30 10:15", "2026-09-29", "2026-10-01", "2026-09-30"),  # live round
    # relative days
    ("yesterday", "2026-09-23 22:32", "2026-09-21", "2026-09-23", "2026-09-22"),
    ("semalam", "2026-08-24 09:25", "2026-08-22", "2026-08-24", "2026-08-23"),
    ("kelmarin", "2026-08-24 09:25", "2026-08-21", "2026-08-23", "2026-08-22"),
    ("day before yesterday", "2026-08-24 09:25", "2026-08-21", "2026-08-23", "2026-08-22"),
    ("hari ini", "2026-07-08 12:39", "2026-07-07", "2026-07-09", "2026-07-08"),
    ("this morning", "2026-07-08 12:39", "2026-07-07", "2026-07-09", "2026-07-08"),
    ("pagi tadi", "2026-07-08 12:39", "2026-07-07", "2026-07-09", "2026-07-08"),
    ("last night", "2026-07-08 01:39", "2026-07-06", "2026-07-08", "2026-07-07"),
    ("malam tadi", "2026-07-08 12:39", "2026-07-06", "2026-07-08", "2026-07-07"),
    ("2 days ago", "2026-08-24 09:25", "2026-08-21", "2026-08-23", "2026-08-22"),
    ("3 hari lepas", "2026-08-24 09:25", "2026-08-20", "2026-08-22", "2026-08-21"),
    # "last <weekday>" is strictly before the received date
    ("last Monday", "2026-08-24 09:25", "2026-08-16", "2026-08-18", "2026-08-17"),  # received on a Monday
    ("last Sunday", "2026-08-24 09:25", "2026-08-22", "2026-08-24", "2026-08-23"),
    ("last Tuesday", "2026-08-24 09:25", "2026-08-17", "2026-08-19", "2026-08-18"),
    ("last Wednesday", "2026-08-24 09:25", "2026-08-18", "2026-08-20", "2026-08-19"),
    ("last Thursday", "2026-08-24 09:25", "2026-08-19", "2026-08-21", "2026-08-20"),
    # MS weekdays (received Wed 2026-09-23)
    ("hari Isnin lepas", "2026-09-23 10:00", "2026-09-20", "2026-09-22", "2026-09-21"),
    ("hari Selasa lepas", "2026-09-23 10:00", "2026-09-21", "2026-09-23", "2026-09-22"),
    ("hari Rabu lepas", "2026-09-23 10:00", "2026-09-15", "2026-09-17", "2026-09-16"),  # same weekday
    ("hari Khamis lepas", "2026-09-23 10:00", "2026-09-16", "2026-09-18", "2026-09-17"),
    ("hari Jumaat lepas", "2026-09-23 10:00", "2026-09-17", "2026-09-19", "2026-09-18"),
    ("hari Sabtu lepas", "2026-09-23 10:00", "2026-09-18", "2026-09-20", "2026-09-19"),
    ("hari Ahad lepas", "2026-09-23 10:00", "2026-09-19", "2026-09-21", "2026-09-20"),
    ("Jumaat lepas", "2026-09-23 10:00", "2026-09-17", "2026-09-19", "2026-09-18"),
    # bare weekday = most recent on or before received
    ("on Monday", "2026-09-23 10:00", "2026-09-20", "2026-09-22", "2026-09-21"),
    ("on Wednesday", "2026-09-23 10:00", "2026-09-22", "2026-09-24", "2026-09-23"),
    ("hari Isnin", "2026-09-23 10:00", "2026-09-20", "2026-09-22", "2026-09-21"),
    # absolute dates
    ("28 July 2026", "2026-09-02 10:00", "2026-07-27", "2026-07-29", "2026-07-28"),
    ("11 Jul", "2026-09-02 10:00", "2026-07-10", "2026-07-12", "2026-07-11"),
    ("11/7", "2026-09-02 10:00", "2026-07-10", "2026-07-12", "2026-07-11"),
    ("11 Julai", "2026-09-02 10:00", "2026-07-10", "2026-07-12", "2026-07-11"),
    ("17/08/2026", "2026-08-24 09:25", "2026-08-16", "2026-08-18", "2026-08-17"),
    ("19 Ogos", "2026-08-24 09:25", "2026-08-18", "2026-08-20", "2026-08-19"),
    ("3 Mac", "2026-06-01 09:00", "2026-03-02", "2026-03-04", "2026-03-03"),
    ("10 Mei", "2026-06-01 09:00", "2026-05-09", "2026-05-11", "2026-05-10"),
    ("1st September", "2026-09-30 09:00", "2026-08-31", "2026-09-02", "2026-09-01"),
    ("Sept 15", "2026-09-30 09:00", "2026-09-14", "2026-09-16", "2026-09-15"),
    ("2026-07-04", "2026-09-30 09:00", "2026-07-03", "2026-07-05", "2026-07-04"),
    ("12 Disember", "2026-01-05 09:00", "2025-12-11", "2025-12-13", "2025-12-12"),  # year inferred back
]

RANGE_CASES = [
    ("last week", "2026-09-23 10:00", "2026-09-10", "2026-09-22"),
    ("minggu lepas", "2026-09-23 10:00", "2026-09-10", "2026-09-22"),
    ("this week", "2026-09-23 10:00", "2026-09-21", "2026-09-23"),  # Mon..today (Wed)
    ("minggu ini", "2026-09-23 10:00", "2026-09-21", "2026-09-23"),
    ("last month", "2026-09-23 10:00", "2026-08-01", "2026-08-31"),
    ("bulan lepas", "2026-02-10 10:00", "2026-01-01", "2026-01-31"),
    ("last month", "2026-01-15 10:00", "2025-12-01", "2025-12-31"),  # across the year boundary
    ("this month", "2026-09-23 10:00", "2026-09-01", "2026-09-23"),
    ("earlier this month", "2026-09-23 10:00", "2026-09-01", "2026-09-10"),
    ("awal bulan ini", "2026-09-05 10:00", "2026-09-01", "2026-09-05"),
    ("bagi bulan Ogos", "2026-09-23 10:00", "2026-08-01", "2026-08-31"),
    ("for June", "2026-07-08 12:39", "2026-06-01", "2026-06-30"),
    ("in September", "2026-09-29 12:00", "2026-09-01", "2026-09-29"),  # current month, clamped
]


@pytest.mark.parametrize(("phrase", "received", "start", "end", "exact"), EXACT_CASES)
def test_exact_day_windows(phrase: str, received: str, start: str, end: str, exact: str) -> None:
    w = resolve_window(phrase, _at(received))
    assert (w.start, w.end, w.exact_day) == (_d(start), _d(end), _d(exact))
    assert w.phrase is not None


@pytest.mark.parametrize(("phrase", "received", "start", "end"), RANGE_CASES)
def test_fuzzy_ranges(phrase: str, received: str, start: str, end: str) -> None:
    w = resolve_window(phrase, _at(received))
    assert (w.start, w.end, w.exact_day) == (_d(start), _d(end), None)


@pytest.mark.parametrize("phrase", [None, "", "sometime recently", "bayan lepas branch"])
def test_no_phrase_is_full_window(phrase: str | None) -> None:
    received = _at("2026-09-23 21:55")
    w = resolve_window(phrase, received)
    assert w.end == received.date()
    assert w.start == received.date() - timedelta(days=MATCH_WINDOW_DAYS + 1)
    assert w.exact_day is None


def test_match_window_is_45_days() -> None:
    assert MATCH_WINDOW_DAYS == 45


def test_cmp_00165_contract_window() -> None:
    w = resolve_window("hari Selasa lepas", _at("2026-08-24 09:25"))
    assert (w.start, w.end, w.exact_day) == (_d("2026-08-17"), _d("2026-08-19"), _d("2026-08-18"))
    assert w.phrase == "hari Selasa lepas"


def test_invalid_calendar_date_is_ignored() -> None:
    assert find_date_phrase("charged on 31/02/2026") is None


def test_amounts_are_not_dates() -> None:
    assert find_date_phrase("charged RM12.10 and RM 1.50 twice, balance 3,582.83") is None


def test_exact_day_beats_range_and_month_name() -> None:
    text = "annual fee for June, and I was charged yesterday, not last month"
    assert find_date_phrase(text) == "yesterday"


def test_earliest_exact_phrase_wins() -> None:
    assert find_date_phrase("on 14 Jul and again last Friday") == "14 Jul"


def test_resolve_window_accepts_full_text() -> None:
    text = "Hi, my transfer of RM 4,687.10 to Aina last Friday did not go through."
    w = resolve_window(text, _at("2026-09-02 16:43"))
    assert w.exact_day == _d("2026-08-28")
    assert w.phrase == "last Friday"


# find_date_phrase on real complaint texts (data/complaints.csv)
REAL = {
    "CMP-00165": "hari Selasa lepas",
    "CMP-00244": "last Friday",
    "CMP-00387": "last Saturday",
    "CMP-00289": "last Friday",
    "CMP-00001": "yesterday",
    "CMP-00003": "15 September 2026",
}


@pytest.mark.parametrize(("cid", "expected"), list(REAL.items()))
def test_find_date_phrase_on_real_complaints(cid: str, expected: str) -> None:
    with (DATA / "complaints.csv").open(encoding="utf-8", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["complaint_id"] == cid)
    assert find_date_phrase(row["subject"] + " " + row["text"]) == expected


def test_no_date_in_service_complaint() -> None:
    assert find_date_phrase("Nobody replied to my email about updating my address for two weeks.") is None
    assert find_date_phrase("Salam, CDM kat branch Taiping rosak seminggu dah, bila nak repair?") is None


def test_gold_transaction_always_inside_window() -> None:
    """Every training complaint's gold txn date lies inside the resolved window (1,506 txn-backed rows)."""
    def read(name: str) -> list[dict[str, str]]:
        with (DATA / name).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    comp = {r["complaint_id"]: r for r in read("complaints.csv")}
    txn = {r["txn_id"]: r for r in read("transactions.csv")}
    checked = 0
    for lab in read("labels_train.csv"):
        gold = txn.get(lab["matched_txn_id"])
        if gold is None:
            continue
        c = comp[lab["complaint_id"]]
        w = resolve_window(c["subject"] + " " + c["text"], _at(c["received_at"]))
        assert w.start <= _at(gold["txn_time"]).date() <= w.end, lab["complaint_id"]
        checked += 1
    assert checked > 1400
