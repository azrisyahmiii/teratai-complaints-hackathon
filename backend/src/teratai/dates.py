"""Date-phrase resolver (SPEC §4.3). P4a stub: returns the CMP-00165 window; C2 replaces it."""

from datetime import date, datetime

from teratai.models import DateWindow


def resolve_window(phrase: str | None, received_at: datetime) -> DateWindow:
    return DateWindow(
        start=date(2026, 8, 17), end=date(2026, 8, 19), exact_day=date(2026, 8, 18), phrase=phrase
    )
