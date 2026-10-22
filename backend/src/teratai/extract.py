"""Regex clue extraction (SPEC §4.2 "Regex clue extraction (code, always)").

`regex_issue(row, category)` fills an `Issue` from the text with regexes only. The LLM extractor (C11) fills the
same schema for the cases where this is not enough. Counterparty stays None: the matcher scores names against
the candidate transactions (SPEC §4.4), so the regex never has to guess a merchant.

Money is parsed straight from the digit string into `Decimal`, never via float.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from teratai import dates
from teratai.models import Category, ComplaintRow, Issue

FeeType = Literal["monthly_service", "debit_annual", "cc_annual"]

# --- amounts ---------------------------------------------------------------------------------------------
_AMOUNT = re.compile(
    r"(?:\b(?:RM|MYR)\s?(?P<a>\d[\d,]*(?:\.\d{1,2})?))|(?:(?P<b>\d[\d,]*(?:\.\d{1,2})?)\s*ringgit\b)",
    re.IGNORECASE,
)
# Approximation marker directly before the amount ("about RM1,500", "lebih kurang RM1,200", "dalam RM400").
_APPROX_BEFORE = re.compile(
    r"(?:about|around|approx\.?|approximately|roughly|circa|~|lebih\s+kurang|kira-kira|sekitar|dalam)\s*$",
    re.IGNORECASE,
)
# An amount the customer *expected* or *received* is not the disputed charge (e.g. "charged RM20 ... thought it
# is only RM10", "withdrew RM1,500 but got RM950"). Looked for between the previous sentence end and the amount.
_NOT_DISPUTED = re.compile(
    r"expected|thought|should\s+be|supposed|only\s+got|only\s+received|dispensed|"
    r"ingat|sepatutnya|bukan|hanya\s+dapat|\bsahaja\b|\bonly\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.?!]\s")


def _amount_of(m: re.Match[str]) -> Decimal:
    return Decimal((m.group("a") or m.group("b")).replace(",", ""))


def amounts(text: str) -> list[tuple[Decimal, bool, bool]]:
    """Every RM amount in order of appearance as (value, approximate, not_disputed)."""
    out: list[tuple[Decimal, bool, bool]] = []
    for m in _AMOUNT.finditer(text):
        before = text[: m.start()]
        approx = _APPROX_BEFORE.search(before) is not None
        sentence_start = max((s.end() for s in _SENTENCE_END.finditer(before)), default=0)
        clause = before[sentence_start:] + text[m.end() : m.end() + 12]
        out.append((_amount_of(m), approx, _NOT_DISPUTED.search(clause) is not None))
    return out


def disputed_amount(text: str) -> tuple[Decimal | None, bool]:
    """The amount most likely disputed, and whether it is approximate.

    Rule: drop amounts the customer says they expected or received ("thought the fee is only RM10"), then take
    the first remaining one; if every amount is dropped, take the first. Measured over train in `__main__`.
    """
    found = amounts(text)
    if not found:
        return None, False
    pool = [a for a in found if not a[2]] or found
    value, approx, _ = pool[0]
    return value, approx


# --- card last 4 -----------------------------------------------------------------------------------------
# "(card ending 2832)", "(kad berakhir 2832)", "Visa ending 9999", "kad nombor 9999", "debit card no. 8888",
# "Mastercard 4321", "last 4 digits of the card: 5555". "account ending 1234" is the recipient's account, not the
# customer's card, so a bare "ending" counts only when no account word comes before it.
_CARD_WORD = r"(?:card|kad|visa|master\s?card|debit|credit|kredit)"
_FILLER = (
    r"(?:card|kad|number|num|no\.?|nombor|my|saya|is|ialah|yang|dengan|with|in|"
    r"ending|berakhir|hujung|akhir|last\s+(?:4|four)\s+digits?|digits?|of\s+the\s+card)"
)
_NOT_DIGIT_TAIL = r"(?![\d.,:/\-]|\s*(?:hrs?|am|pm|jam|ringgit|sen|%))"
_CARD_LAST4 = re.compile(
    rf"\b{_CARD_WORD}\b(?:\s+{_FILLER}(?=[\s:#]))*\s*[:#]?\s*(?P<d>\d{{4}}){_NOT_DIGIT_TAIL}", re.IGNORECASE
)
_CARD_ENDING = re.compile(
    r"(?<!account )(?<!akaun )(?<!acc )(?<!acct )(?<!a/c )\b(?:ending(?:\s+in|\s+with)?|berakhir(?:\s+dengan)?|hujung)"
    rf"\s+(?P<d>\d{{4}}){_NOT_DIGIT_TAIL}",
    re.IGNORECASE,
)
_CARD_LAST4_ALT = re.compile(
    rf"(?:\*{{2,}}|x{{2,}}|last\s+(?:4|four)\s+digits?(?:\s+is)?)\s*(?P<d>\d{{4}}){_NOT_DIGIT_TAIL}", re.IGNORECASE
)
# A bare year is not a card number: 2024-2030 counts only after an explicit "ending" / "number" style word.
_YEAR = re.compile(r"20(?:2\d|30)$")
_EXPLICIT = re.compile(r"ending|berakhir|hujung|akhir|number|nombor|\bno\b|digit", re.IGNORECASE)


def card_last4(text: str) -> str | None:
    for rx in (_CARD_LAST4, _CARD_ENDING, _CARD_LAST4_ALT):
        for m in rx.finditer(text):
            d = m.group("d")
            if _YEAR.match(d) and not _EXPLICIT.search(m.group(0)):
                continue
            return d
    return None


# --- third party (SPEC §6 "Wrong customer": "my friend's account") ------------------------------------------
_RELATIVES = (
    r"friend|wife|husband|spouse|partner|son|daughter|mother|father|mom|mum|dad|brother|sister|parents?|uncle|aunt|"
    r"aunty|cousin|grandmother|grandfather|colleague|co-worker|coworker|boss|employer|neighbou?r|relative|"
    r"girlfriend|boyfriend"
)
_RELATIVES_MS = (
    r"kawan|rakan|isteri|suami|pasangan|adik|abang|kakak|ibu|bapa|ayah|mak|abah|anak|nenek|datuk|bapa\s+saudara|"
    r"mak\s+saudara|pak\s+cik|mak\s+cik|sepupu|majikan|bos|jiran|saudara|rakan\s+sekerja"
)
_OWNED = r"(?:\w+\s+){0,2}?"
_POSS_CARD = re.compile(
    rf"\b(?:{_RELATIVES})(?:'|’)?s\s+{_OWNED}(?:card|visa|mastercard|debit)\b", re.IGNORECASE
)
_POSS_ACCOUNT = re.compile(rf"\b(?:{_RELATIVES})(?:'|’)?s\s+{_OWNED}(?:account|acc|acct|a/c)\b", re.IGNORECASE)
_MS_CARD = re.compile(rf"\b(?:kad(?:\s+\w+)?)\s+(?:milik\s+)?(?:{_RELATIVES_MS})\b", re.IGNORECASE)
_MS_ACCOUNT = re.compile(rf"\b(?:akaun|account)\s+(?:milik\s+)?(?:{_RELATIVES_MS})\b", re.IGNORECASE)
_CARD_BELONGS = re.compile(
    rf"\b(?:card|account|kad|akaun)\s+(?:belongs?\s+to|is\s+(?:under|in\s+the\s+name\s+of)|milik)\s+(?:my\s+)?(?:{_RELATIVES}|{_RELATIVES_MS})",
    re.IGNORECASE,
)
_BEHALF = re.compile(r"on\s+behalf\s+of|bagi\s+pihak|mewakili|acting\s+for", re.IGNORECASE)
# "to my friend's account" / "ke akaun kawan saya" is the payee of a transfer, which is the customer's own business.
_PAYEE_LEAD = re.compile(r"\b(?:to|into|for|ke|kepada|untuk)\s+(?:(?:my|the)\s+)?$", re.IGNORECASE)


def _is_payee(text: str, m: re.Match[str]) -> bool:
    return _PAYEE_LEAD.search(text[max(0, m.start() - 12) : m.start()]) is not None


def third_party_cue(text: str) -> bool:
    """The card / account in the complaint belongs to someone else, or the writer acts for someone else.

    Cues: "my friend's card", "kad kawan saya", "akaun adik saya", "on behalf of". A friend's *account* that
    is the payee of a transfer ("to my friend's account") does not count: that is the customer's own transfer.
    """
    if _BEHALF.search(text) or _POSS_CARD.search(text) or _MS_CARD.search(text) or _CARD_BELONGS.search(text):
        return True
    for rx in (_POSS_ACCOUNT, _MS_ACCOUNT):
        for m in rx.finditer(text):
            if not _is_payee(text, m):
                return True
    return False


# --- card in possession ----------------------------------------------------------------------------------
_IN_POSSESSION = re.compile(
    r"in\s+(?:my|their|his|her)\s+possession|still\s+with\s+me|kad\s+masih\s+ada|"
    r"masih\s+(?:ada\s+)?(?:dengan|pada)\s+saya|dalam\s+simpanan|have\s+the\s+card|card\s+is\s+safe",
    re.IGNORECASE,
)
_NOT_IN_POSSESSION = re.compile(
    r"\b(?:lost|stolen|misplaced|missing)\b|\bhilang\b|\bdicuri\b|\bcurian\b|\bterpelanting\b", re.IGNORECASE
)


def card_in_possession(text: str) -> bool | None:
    if _NOT_IN_POSSESSION.search(text):
        return False
    return True if _IN_POSSESSION.search(text) else None


# --- fees ------------------------------------------------------------------------------------------------
_FEE_MONTHLY = re.compile(
    r"monthly\s+(?:service|fee|charge)|service\s+charge|caj\s+perkhidmatan|caj\s+bulanan|yuran\s+bulanan",
    re.IGNORECASE,
)
_FEE_CC = re.compile(r"credit\s+card|kad\s+kredit|\bcc\b", re.IGNORECASE)
_FEE_DEBIT = re.compile(r"debit(?:\s+card)?|kad\s+debit", re.IGNORECASE)

# EN + MS month names. "may" is also an English verb, so it only counts after a month cue word.
_MONTHS: dict[str, int] = {
    "january": 1, "januari": 1, "jan": 1, "february": 2, "februari": 2, "feb": 2, "march": 3, "mac": 3,
    "april": 4, "apr": 4, "mei": 5, "june": 6, "jun": 6, "july": 7, "julai": 7, "jul": 7,
    "august": 8, "ogos": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10, "oktober": 10,
    "oct": 10, "okt": 10, "november": 11, "nov": 11, "december": 12, "disember": 12, "dec": 12, "dis": 12,
}  # fmt: skip
_MONTH_NAME = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_RE = re.compile(rf"\b(?P<m>{_MONTH_NAME})\b(?:\s+(?P<y>20\d\d))?", re.IGNORECASE)
_MAY_RE = re.compile(r"\b(?:bulan|in|for|of)\s+may\b(?:\s+(?P<y>20\d\d))?", re.IGNORECASE)
_LAST_MONTH = re.compile(r"last\s+month|bulan\s+(?:lepas|lalu)", re.IGNORECASE)
_THIS_MONTH = re.compile(r"this\s+month|bulan\s+ini", re.IGNORECASE)


def _year_for(month: int, received: datetime, explicit: str | None) -> int:
    if explicit:
        return int(explicit)
    return received.year if month <= received.month else received.year - 1


def fee_type(text: str) -> FeeType | None:
    if _FEE_MONTHLY.search(text):
        return "monthly_service"
    if re.search(r"annual|tahunan|yearly", text, re.IGNORECASE):
        if _FEE_CC.search(text):
            return "cc_annual"
        if _FEE_DEBIT.search(text):
            return "debit_annual"
    return None


def fee_month(text: str, received_at: datetime) -> str | None:
    """"YYYY-MM" of the month the fee was charged: a month name, or last/this month vs `received_at`."""
    m = _MONTH_RE.search(text)
    if m:
        month = _MONTHS[m.group("m").lower()]
        return f"{_year_for(month, received_at, m.group('y')):04d}-{month:02d}"
    mm = _MAY_RE.search(text)
    if mm:
        return f"{_year_for(5, received_at, mm.group('y')):04d}-05"
    if _LAST_MONTH.search(text):
        y, mo = (received_at.year, received_at.month - 1) if received_at.month > 1 else (received_at.year - 1, 12)
        return f"{y:04d}-{mo:02d}"
    if _THIS_MONTH.search(text):
        return f"{received_at.year:04d}-{received_at.month:02d}"
    return None


# --- the Issue -------------------------------------------------------------------------------------------


def regex_issue(row: ComplaintRow, category: Category) -> Issue:
    """Clues from the text by regex alone. The category is decided elsewhere (classify.py)."""
    text = f"{row.subject} {row.text}".strip()
    amount, approx = disputed_amount(text)
    is_fee = category == "FEE_DISPUTE"
    return Issue(
        category=category,
        amount=amount,
        amount_approx=approx,
        counterparty=None,
        date_phrase=dates.find_date_phrase(text),
        card_last4=card_last4(text),
        fee_type=fee_type(text) if is_fee else None,
        fee_month=fee_month(text, row.received_at) if is_fee else None,
        card_in_possession=card_in_possession(text),
    )


def _main() -> None:
    """Measure the regex clues against the gold transaction over the training complaints."""
    from teratai import data

    hit = tot = 0
    miss: list[str] = []
    fee_ok = fee_tot = month_ok = 0
    for cid, lab in data.labels().items():
        if not lab.matched_txn_id:
            continue
        row = data.complaint(cid)
        issue = regex_issue(row, lab.category)  # type: ignore[arg-type]
        gold = data.txn(lab.matched_txn_id)
        if lab.category == "FEE_DISPUTE":
            fee_tot += 1
            want_type = {"Monthly service charge": "monthly_service", "Debit card annual fee": "debit_annual"}
            desc = gold.description
            want = next((v for k, v in want_type.items() if desc.startswith(k)), "cc_annual")
            fee_ok += issue.fee_type == want
            month_ok += issue.fee_month == gold.txn_time.strftime("%Y-%m")
        if issue.amount is None:
            continue  # fee disputes with no RM amount are matched by type + month
        tot += 1
        if abs(issue.amount - gold.amount) <= Decimal("0.005") or (
            issue.amount_approx and abs(issue.amount - gold.amount) <= max(gold.amount * Decimal("0.05"), Decimal(20))
        ):
            hit += 1
        else:
            miss.append(f"{cid} text={issue.amount} gold={gold.amount} approx={issue.amount_approx}")
    print(f"amount hit rate (text amount within the matcher tolerance of the gold txn): {hit}/{tot} = {hit / tot:.4f}")
    print(f"fee_type correct {fee_ok}/{fee_tot}; fee_month correct {month_ok}/{fee_tot}")
    print("\n".join(miss[:10]))


if __name__ == "__main__":
    _main()
