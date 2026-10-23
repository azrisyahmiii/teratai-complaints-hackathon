"""Date-phrase resolver (SPEC §4.3). Pure functions, no I/O, EN + MS.

Two entry points:
- `find_date_phrase(text)`: first recognised date phrase in free text (regex path).
- `resolve_window(phrase, received_at)`: phrase (or free text containing one) -> `DateWindow`.

All dates are naive MYT, relative to the received date. Exact day -> [day-1, day+1] with `exact_day` set
(the matcher scores an exact-day hit higher); fuzzy ranges (last week, last month ...) carry no `exact_day`.
"""

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from teratai.config import MATCH_WINDOW_DAYS
from teratai.models import DateWindow
from teratai.textnorm import normalise

# Weekday index follows date.weekday(): Monday = 0.
_WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "isnin": 0, "selasa": 1, "rabu": 2, "khamis": 3, "jumaat": 4, "sabtu": 5, "ahad": 6,
    # Short forms used in chat. The rules below only read a weekday after last/on/this/hari or before lepas,
    # so "sat" / "sun" / "wed" as ordinary words are not read as dates.
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
    "sab": 5, "jum": 4, "rab": 2, "kha": 3, "isn": 0, "sel": 1,
}  # fmt: skip
_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    "januari": 1, "februari": 2, "mac": 3, "mei": 5, "julai": 7, "ogos": 8, "oktober": 10, "okt": 10,
    "disember": 12, "dis": 12,
}  # fmt: skip


def _alt(words: dict[str, int]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_WD = rf"(?P<wd>{_alt(_WEEKDAYS)})"
_MON = rf"(?P<mon>{_alt(_MONTHS)})"

# Resolver result: (start, end, exact_day).
_Span = tuple[date, date, date | None]
_Resolver = Callable[[re.Match[str], date], _Span | None]

# Specificity class: lower wins when a text holds several phrases.
_EXACT, _RANGE, _MONTH_NAME = 0, 1, 2


def _day(d: date) -> _Span:
    return d - timedelta(days=1), d + timedelta(days=1), d


def _month_span(year: int, month: int, today: date) -> _Span:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, min(last, today), None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_year(month: int, day: int, today: date) -> date | None:
    """Year omitted: the most recent such calendar date (1 day of slack into the future)."""
    this_year = _safe_date(today.year, month, day)
    if this_year is not None and this_year <= today + timedelta(days=1):
        return this_year
    return _safe_date(today.year - 1, month, day)


def _expand_year(y: int) -> int:
    return y + 2000 if y < 100 else y


def _last_weekday(wd: int, today: date) -> date:
    """Most recent `wd` strictly before `today` (received on that weekday -> 7 days earlier)."""
    back = (today.weekday() - wd) % 7 or 7
    return today - timedelta(days=back)


def _recent_weekday(wd: int, today: date) -> date:
    """Most recent `wd` on or before `today` ("on Friday", "this Friday")."""
    return today - timedelta(days=(today.weekday() - wd) % 7)


def _r_dmy_name(m: re.Match[str], today: date) -> _Span | None:
    month, dd = _MONTHS[m["mon"].lower()], int(m["d"])
    if m["y"]:
        d = _safe_date(int(m["y"]), month, dd)
    else:
        d = _infer_year(month, dd, today)
    return _day(d) if d else None


def _r_name_dy(m: re.Match[str], today: date) -> _Span | None:
    month, dd = _MONTHS[m["mon"].lower()], int(m["d"])
    d = _safe_date(int(m["y"]), month, dd) if m["y"] else _infer_year(month, dd, today)
    return _day(d) if d else None


def _r_numeric(m: re.Match[str], today: date) -> _Span | None:
    dd, month = int(m["d"]), int(m["m"])  # day first (data uses 17/08/2026)
    d = _safe_date(_expand_year(int(m["y"])), month, dd) if m["y"] else _infer_year(month, dd, today)
    return _day(d) if d else None


def _r_iso(m: re.Match[str], today: date) -> _Span | None:
    d = _safe_date(int(m["y"]), int(m["m"]), int(m["d"]))
    return _day(d) if d else None


def _offset(days: int) -> _Resolver:
    return lambda _m, today: _day(today + timedelta(days=days))


def _r_n_days_ago(m: re.Match[str], today: date) -> _Span | None:
    n = int(m["n"])
    return _day(today - timedelta(days=n)) if 0 < n <= 60 else None


def _r_last_weekday(m: re.Match[str], today: date) -> _Span | None:
    return _day(_last_weekday(_WEEKDAYS[m["wd"].lower()], today))


def _r_recent_weekday(m: re.Match[str], today: date) -> _Span | None:
    return _day(_recent_weekday(_WEEKDAYS[m["wd"].lower()], today))


def _r_weekday_last_week(m: re.Match[str], today: date) -> _Span | None:
    """"Tuesday last week": that weekday in the calendar week before this one."""
    monday = today - timedelta(days=today.weekday())
    return _day(monday - timedelta(days=7) + timedelta(days=_WEEKDAYS[m["wd"].lower()]))


def _r_weeks_ago(m: re.Match[str], today: date) -> _Span | None:
    n = int(m["n"])
    if not 0 < n <= 8:
        return None
    centre = today - timedelta(days=7 * n)
    return centre - timedelta(days=3), centre + timedelta(days=3), None  # "2 weeks ago" is fuzzy


def _r_day_of_month(m: re.Match[str], today: date) -> _Span | None:
    """"15hb": the most recent 15th (this month, or last month when it has not come yet)."""
    dd = int(m["d"])
    d = _safe_date(today.year, today.month, dd)
    if d is None or d > today + timedelta(days=1):
        prev = today.replace(day=1) - timedelta(days=1)
        d = _safe_date(prev.year, prev.month, dd)
    return _day(d) if d else None


def _r_last_week(_m: re.Match[str], today: date) -> _Span | None:
    return today - timedelta(days=13), today - timedelta(days=1), None


def _r_this_week(_m: re.Match[str], today: date) -> _Span | None:
    return today - timedelta(days=today.weekday()), today, None


def _r_last_month(_m: re.Match[str], today: date) -> _Span | None:
    prev = today.replace(day=1) - timedelta(days=1)
    return _month_span(prev.year, prev.month, today)


def _r_this_month(_m: re.Match[str], today: date) -> _Span | None:
    return today.replace(day=1), today, None


def _r_early_month(_m: re.Match[str], today: date) -> _Span | None:
    return today.replace(day=1), min(today, today.replace(day=10)), None


def _r_month_name(m: re.Match[str], today: date) -> _Span | None:
    month = _MONTHS[m["mon"].lower()]
    if m["y"]:
        year = int(m["y"])
    else:
        year = today.year if month <= today.month else today.year - 1
    return _month_span(year, month, today)


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    klass: int
    resolve: _Resolver


def _rule(pattern: str, klass: int, resolve: _Resolver) -> _Rule:
    return _Rule(re.compile(pattern, re.IGNORECASE), klass, resolve)


_Y = r"(?:,?\s+(?P<y>\d{4}))?"
_RULES: list[_Rule] = [
    # Absolute dates.
    _rule(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}\b\.?{_Y}", _EXACT, _r_dmy_name),
    _rule(rf"\b{_MON}\b\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?!\d){_Y}", _EXACT, _r_name_dy),
    _rule(r"(?<![\d./-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d-])", _EXACT, _r_iso),
    # Day first. "." and "-" only with a 4-digit year, so amounts like RM12.10 are never read as dates.
    _rule(
        r"(?<![\d./-])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])",
        _EXACT,
        _r_numeric,
    ),
    _rule(r"(?<![\d./-])(?P<d>\d{1,2})[.-](?P<m>\d{1,2})[.-](?P<y>\d{4})(?![\d/])", _EXACT, _r_numeric),
    # Relative days.
    _rule(r"\b(?:kelmarin|day before yesterday)\b", _EXACT, _offset(-2)),
    _rule(r"\b(?:yesterday|semalam|last night|malam tadi)\b", _EXACT, _offset(-1)),
    _rule(
        r"\b(?:today|hari ini|tonight|malam ini|this (?:morning|afternoon|evening)|"
        r"(?:pagi|petang|tengah hari) (?:tadi|ini)|tadi)\b",
        _EXACT,
        _offset(0),
    ),
    _rule(r"\b(?P<n>\d{1,2})\s+(?:days? ago|hari (?:lepas|yang lalu|lalu))", _EXACT, _r_n_days_ago),
    _rule(r"\b(?P<n>\d{1,2})\s*(?:weeks?|minggu)\s+(?:ago|lepas|lalu)\b", _RANGE, _r_weeks_ago),
    _rule(r"(?<![\d./-])(?P<d>\d{1,2})\s?hb\b", _EXACT, _r_day_of_month),
    # Weekdays: "last Friday", "hari Selasa lepas" / "Selasa lepas" -> strictly before today.
    _rule(
        rf"\b{_WD}\s+(?:last\s+week|minggu\s+(?:yang\s+)?(?:lepas|lalu))\b", _EXACT, _r_weekday_last_week
    ),
    _rule(rf"\blast\s+{_WD}\b", _EXACT, _r_last_weekday),
    _rule(rf"\b(?:hari\s+)?{_WD}\s+(?:yang\s+)?lepas\b", _EXACT, _r_last_weekday),
    # "on Friday", "hari Jumaat", "this Friday", "Jumaat ini" -> most recent on or before today.
    _rule(rf"\b(?:on|pada|hari|this)\s+{_WD}\b", _EXACT, _r_recent_weekday),
    _rule(rf"\b{_WD}\s+ini\b", _EXACT, _r_recent_weekday),
    # Fuzzy ranges.
    _rule(r"\b(?:last week|previous week|minggu (?:yang )?(?:lepas|lalu))\b", _RANGE, _r_last_week),
    _rule(r"\b(?:this week|minggu ini)\b", _RANGE, _r_this_week),
    _rule(r"\b(?:last month|previous month|bulan (?:yang )?(?:lepas|lalu))\b", _RANGE, _r_last_month),
    _rule(r"\b(?:earlier this month|awal bulan ini)\b", _RANGE, _r_early_month),
    _rule(r"\b(?:this month|bulan ini)\b", _RANGE, _r_this_month),
    # Month name only ("bagi bulan Ogos", "for June"): whole calendar month.
    _rule(rf"\b(?:bulan|for|in|during|of)\s+{_MON}\b(?:\s+(?P<y>\d{{4}}))?", _MONTH_NAME, _r_month_name),
]  # fmt: skip


def _scan(text: str, received: date) -> tuple[str, _Span] | None:
    """Best phrase in `text`: most specific class, then earliest, then longest."""
    best: tuple[tuple[int, int, int], str, _Span] | None = None
    text = normalise(text)  # clue-only: SMS short forms ("lps", "smlm") become words the rules know
    for rule in _RULES:
        for m in rule.pattern.finditer(text):
            span = rule.resolve(m, received)
            if span is None:
                continue
            key = (rule.klass, m.start(), -(m.end() - m.start()))
            if best is None or key < best[0]:
                best = (key, m.group(0), span)
    return None if best is None else (best[1], best[2])


_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "lapan": 8, "sembilan": 9,
    "sepuluh": 10,
}  # fmt: skip


def phrase_supported(canonical: str, text: str) -> bool:
    """A canonical date form (the model's closed vocabulary) is backed by the text.

    Every weekday, month and number it names must occur in the text in some surface form (English or Malay name,
    short form, "11/7", a number word). Relative words with none of these ("yesterday") are backed by nothing more
    than the caller's check that the customer's own words exist in the text.
    """
    canon = canonical.lower()
    norm = normalise(text).lower()
    toks = re.findall(r"[^\W_]+", norm)
    want_wd = {_WEEKDAYS[t] for t in re.findall(r"[^\W\d_]+", canon) if t in _WEEKDAYS}
    have_wd = {_WEEKDAYS[t] for t in toks if t in _WEEKDAYS}
    if not want_wd <= have_wd:
        return False
    want_mon = {_MONTHS[t] for t in re.findall(r"[^\W\d_]+", canon) if t in _MONTHS}
    have_mon = {_MONTHS[t] for t in toks if t in _MONTHS}
    have_mon |= {int(m) for m in re.findall(r"\b\d{1,2}\s?[/.-]\s?(\d{1,2})\b", norm)}
    if not want_mon <= have_mon:
        return False
    nums = set(re.findall(r"\d+", norm)) | {str(_NUMBER_WORDS[t]) for t in toks if t in _NUMBER_WORDS}
    nums |= {n.lstrip("0") for n in nums}
    return all(n.lstrip("0") in nums for n in re.findall(r"\d+", canon))


def find_date_phrase(text: str) -> str | None:
    """First recognised date phrase in free text (EN + MS), or None.

    "Recognised" = would resolve to a valid date window; exact-day phrases win over ranges, and ranges over
    bare month names. The year-less forms are validated against a nominal received date (mid-2026).
    """
    found = _scan(text, date(2026, 9, 30))
    return None if found is None else found[0]


def full_window(received_at: datetime, phrase: str | None = None) -> DateWindow:
    """No usable phrase: MATCH_WINDOW_DAYS before the received date, +1 day of slack, end = received date."""
    today = received_at.date()
    return DateWindow(start=today - timedelta(days=MATCH_WINDOW_DAYS + 1), end=today, phrase=phrase)


def resolve_window(phrase: str | None, received_at: datetime) -> DateWindow:
    """Resolve a date phrase (or a whole complaint text containing one) against `received_at`."""
    if not phrase:
        return full_window(received_at)
    found = _scan(phrase, received_at.date())
    if found is None:
        return full_window(received_at)
    matched, (start, end, exact) = found
    return DateWindow(start=start, end=end, exact_day=exact, phrase=matched)
