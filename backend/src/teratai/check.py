"""Decision-bound self-check (SPEC §4.7, checks 1-5). Pure: text + FactSheet in, CheckResult out.

Only facts of THIS case are allowed in a reply: the ids and amounts on the `FactSheet` (plus the auto-refund limit and the
verified regulatory contacts below), never the customer's whole history. That is stricter than `starter/check_reply.py`.

Every list below (refund verbs, jargon, allow-lists) is data: a new entry is a new line, not a code change.
`token_verdicts` is the single source of truth: `check_reply` turns its unverified spans into issues, and the UI
uses the same spans to paint tokens green (verified) or red (not in evidence), SPEC §13.5.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from teratai import config, lang
from teratai.models import CheckIssue, CheckResult, FactSheet
from teratai.templates import en as _en
from teratai.templates import ms as _ms

# --- verified regulatory facts (web-checked 2026-10-22; BA to re-confirm in eval/regulatory_facts.md) ------------
# NSRC hotline 997:  https://www.bnm.gov.my/faqs/scams and https://nfcc.jpm.gov.my/index.php/en/about-nsrc
# FMOS (formerly OFS, renamed 6 Sep 2024, launched 17 Jan 2025): https://www.fmos.org.my/en/who-we-are/
# BNMLINK (formerly BNMTELELINK, renamed July 2023), 1-300-88-5465: https://www.bnm.gov.my/-/bnmlink-services-remain-available
ALLOWED_PHONE_DIGITS: frozenset[str] = frozenset({"997", "1300885465"})
ALLOWED_URL_HOSTS: frozenset[str] = frozenset({"fmos.org.my", "bnm.gov.my"})
# e-mail addresses are never allowed unless listed here in full (none is verified)
ALLOWED_EMAILS: frozenset[str] = frozenset()

MAX_REPLY_CHARS = 1200
MIXED_MAX_OTHER_SHARE = (
    0.20  # a MIXED reply passes only if at most 20% of its stopword hits are the other language
)
AMOUNT_TOLERANCE = Decimal("0.005")

# --- negation: a refusal must directly govern the verb, inside the same sentence --------------------------------
# "unable to refund", "has not been refunded", "tidak dapat memulangkan": the negation, then only auxiliaries, then the verb.
NEGATION_WORDS = r"no|not|never|cannot|can't|unable|won't|wouldn't|couldn't|tidak|tak|belum|bukan|tiada"
NEGATION_AUX = r"yet|be|been|being|get|got|to|able|going|ever|dapat|boleh|akan|lagi"
_NEGATED_TAIL = re.compile(rf"\b(?:{NEGATION_WORDS})\b(?:\s+(?:{NEGATION_AUX}))*\s*$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?;](?=\s|$)|\n")
_FUTURE_TAIL = re.compile(r"\b(?:will|shall|would|going\s+to|akan)(?:\s+be)?\s*$", re.IGNORECASE)

# --- transaction ids and amounts ---------------------------------------------------------------------------------
_TXN = re.compile(r"TXN-\d{7}")  # the canonical id format (what the fact sheet holds)
_TXN_LOOSE = re.compile(r"(?<![A-Za-z])TXN[\s_\-]{0,2}(\d+)", re.IGNORECASE)  # any spelling of an id
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_SEP = r"[\s:\-]*"  # "RM 600", "RM:600", "RM-600"
_AMOUNT = re.compile(
    rf"(?<![A-Za-z])(?:RM|MYR){_SEP}(?P<a>{_NUM})(?P<ak>k\b)?"  # RM600, MYR 600, RM:600
    rf"|(?<![A-Za-z])ringgit{_SEP}(?P<c>{_NUM})(?P<ck>k\b)?"  # ringgit 600
    rf"|(?<![\w.,/\-])(?P<b>{_NUM})(?P<bk>k)?\s?(?:ringgit|MYR|RM)\b",  # 600 ringgit, 600 MYR, 600 RM
    re.IGNORECASE,
)
# "RM550-600": the second number of a range has no currency sign of its own
_RANGE_TAIL = re.compile(rf"\s*[-\u2013\u2014]\s*(?P<n>{_NUM})(?P<k>k\b)?", re.IGNORECASE)
_NOT_A_RANGE = re.compile(
    r"[-/]\d|\s*(?:working|business|days?|hari|jam|hours?|months?|bulan|weeks?|minggu)\b", re.IGNORECASE
)

# --- refund wording ------------------------------------------------------------------------------------------------
# Promises, EN + MS. Forbidden unless the outcome is REFUND.
REFUND_VERBS: tuple[str, ...] = (
    r"\b(?:will|shall|would)\s+(?:be\s+)?refund(?:ed)?\b",
    r"\bwe(?:'ll|\s+will)?\s+refund\b",
    r"\b(?:will|shall)\s+(?:be\s+)?credited\b",
    r"\bis\s+being\s+(?:credited|refunded)\b",
    r"\bcredit\s+(?:back\s+)?(?:to\s+)?your\s+account\b",
    r"\bpay(?:ing)?\s+(?:you\s+)?back\b",
    r"\brefund\s+(?:will\s+be|has\s+been|have\s+been|is\s+being)\s+(?:issued|approved|processed|initiated|paid|credited)\b",
    r"\breturn\s+(?:your|the)\s+(?:money|funds?|payment)\b",
    r"\breimburs(?:e|es|ing|ement)\b",
    r"\b(?:issue|process|processing|arrange)\s+(?:you\s+)?(?:a|the|your)\s+refund\b",
    r"\bmembayar\s+balik\b",
    r"\bbayar\s+balik\b",
    r"\bbayaran\s+balik\b",
    r"\bmemulangkan\b",
    r"\bmengembalikan\b",
    r"\bmengkreditkan\b",
)
# Past-tense / passive forms. Also forbidden, EXCEPT on a DECLINE that states an earlier reversal (SPEC §6: "already
# refunded on <reversal date>"): there they are factual when the same sentence cites the reversal (id, date or word).
FACTUAL_PAST_VERBS: tuple[str, ...] = (
    r"\brefunded\b",
    r"\b(?:has|have|had|was|were)\s+(?:been\s+)?credited\b",
    r"\bcredited\s+(?:back\b|(?:to\s+)?your\s+account\b)",
    r"\bpaid\s+(?:you\s+)?back\b",
    r"\breturned\s+(?:your|the)\s+(?:money|funds?|payment)\b",
    r"\breimbursed\b",
    r"\bdikreditkan(?:\s+semula)?\b",
    r"\bdikembalikan\b",
    r"\bdipulangkan\b",
    r"\bdibayar\s+balik\b",
)
_REFUND_RES = [re.compile(p, re.IGNORECASE) for p in REFUND_VERBS]
_FACTUAL_RES = [re.compile(p, re.IGNORECASE) for p in FACTUAL_PAST_VERBS]
_REVERSAL_WORDS = re.compile(r"\brevers(?:al|ed|e)\b|\bpembalikan\b|\bdibalikkan\b", re.IGNORECASE)

# Internal terms that must never reach a customer.
JARGON: tuple[str, ...] = (
    r"\b(?:AUTO_RESOLVE|HUMAN_APPROVAL|FRAUD_TEAM|NEEDS_INFO|INFO_ONLY)\b",
    r"\b[A-Z]{3,}_[A-Z_]{3,}\b",  # category / enum names, e.g. DUPLICATE_CHARGE
    r"\b[A-Z_]{3,}\.(?:REFUND|DECLINE|INVESTIGATE|INFO_ONLY)\b",  # rule ids
    r"\brule[ _-]?id\b",
    r"\bP[123]\b",  # priority levels
)
_JARGON_RES = [re.compile(p) for p in JARGON]
PLACEHOLDERS: tuple[str, ...] = (r"\{[^{}\n]*\}", r"\[\[[^\]\n]*\]\]", r"%\([a-z_]+\)s")
_PLACEHOLDER_RES = [re.compile(p) for p in PLACEHOLDERS]

# --- phone numbers, URLs, e-mail -------------------------------------------------------------------------------------
# phone numbers: 7+ digits with the usual separators, or a 3-5 digit short code right after "call", "hubungi", ...
_PHONE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().\-]{5,}\d(?!\w)")
_SHORT_CODE = re.compile(
    r"\b(?:call|dial|phone|hotline|whatsapp|sms|hubungi|telefon|talian|dail)\b\W+(?:[A-Za-z]+\W+){0,3}?(\d{3,5})\b",
    re.IGNORECASE,
)
_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
# Any e-mail, scheme URL, www. host, or bare host.tld[/path] for ANY top-level domain. A bare host needs an all-lowercase
# or all-uppercase TLD, so a missing space after a full stop ("account.We") is not read as a link.
_URL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+"
    r"|(?i:(?:https?|ftp)://[^\s,;)]+)"
    r"|(?i:www\.[^\s,;)]+)"
    r"|(?<![\w@./\-])(?:[A-Za-z0-9\-]+\.)+(?:[a-z]{2,24}|[A-Z]{2,24})\b(?:/[^\s,;)]*)?"
)
_URL_TRAILING = ".,;:!?\"'"


class TokenVerdict(BaseModel):
    """One checked token with its position in the text, for green / red highlighting."""

    start: int
    end: int
    text: str
    kind: Literal["TXN_ID", "AMOUNT", "PHONE_URL"]
    verified: bool
    value: Decimal | None = None  # the money value of an AMOUNT token


def _allowed_ids(facts: FactSheet) -> set[str]:
    return {v for v in facts.ids.values() if _TXN.fullmatch(v)}


def _allowed_amounts(facts: FactSheet) -> set[Decimal]:
    return {*facts.amounts.values(), facts.refund_myr, config.AUTO_REFUND_LIMIT_MYR}


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        chars[s:e] = " " * (e - s)
    return "".join(chars)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _to_decimal(raw: str | None, thousand: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        value = Decimal(raw.replace(",", ""))
    except ArithmeticError:
        return None
    return value * 1000 if thousand else value


def _amount_tokens(text: str) -> list[tuple[int, int, Decimal | None]]:
    """(start, end, value) of every money amount: sign before or after the number, any separator, `k`, range tails."""
    out: list[tuple[int, int, Decimal | None]] = []
    consumed = 0
    for m in _AMOUNT.finditer(text):
        if m.start() < consumed:
            continue
        value = _to_decimal(
            m.group("a") or m.group("c") or m.group("b"), m.group("ak") or m.group("ck") or m.group("bk")
        )
        out.append((m.start(), m.end(), value))
        consumed = m.end()
        tail = _RANGE_TAIL.match(text, m.end())
        if tail and not _NOT_A_RANGE.match(text, tail.end()):
            out.append((tail.start("n"), tail.end(), _to_decimal(tail.group("n"), tail.group("k"))))
            consumed = tail.end()
    return out


def _url_allowed(url: str) -> bool:
    low = url.lower()
    if "://" not in low and "@" in low:  # e-mail
        return low in ALLOWED_EMAILS
    host = re.sub(r"^[a-z]+://", "", low).split("/")[0].split("@")[-1].split(":")[0].rstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_URL_HOSTS)


def token_verdicts(text: str, facts: FactSheet) -> list[TokenVerdict]:
    """Every transaction id, money amount, phone number and URL in `text`, each marked verified or not."""
    out: list[TokenVerdict] = []
    ids, amounts = _allowed_ids(facts), _allowed_amounts(facts)
    taken: list[tuple[int, int]] = []
    for m in _TXN_LOOSE.finditer(text):
        ok = f"TXN-{m.group(1)}" in ids
        out.append(TokenVerdict(start=m.start(), end=m.end(), text=m.group(), kind="TXN_ID", verified=ok))
        taken.append(m.span())
    unmasked = _mask(text, taken)
    for start, end, value in _amount_tokens(unmasked):
        ok = value is not None and any(abs(value - a) <= AMOUNT_TOLERANCE for a in amounts)
        out.append(
            TokenVerdict(start=start, end=end, text=text[start:end], kind="AMOUNT", verified=ok, value=value)
        )
        taken.append((start, end))
    rest = _mask(text, taken)
    for m in _URL.finditer(rest):
        token = m.group().rstrip(_URL_TRAILING)
        out.append(
            TokenVerdict(
                start=m.start(),
                end=m.start() + len(token),
                text=token,
                kind="PHONE_URL",
                verified=_url_allowed(token),
            )
        )
        taken.append((m.start(), m.start() + len(token)))
    rest = _mask(text, taken)
    rest = _DATE_LIKE.sub(lambda m: " " * len(m.group()), rest)
    phones: list[tuple[int, int]] = []
    for m in _PHONE.finditer(rest):
        if len(_digits(m.group())) >= 7:
            phones.append(m.span())
            ok = _digits(m.group()) in ALLOWED_PHONE_DIGITS
            out.append(
                TokenVerdict(start=m.start(), end=m.end(), text=m.group(), kind="PHONE_URL", verified=ok)
            )
    for m in _SHORT_CODE.finditer(rest):
        s, e = m.span(1)
        if not any(ps <= s < pe for ps, pe in phones):
            out.append(
                TokenVerdict(
                    start=s,
                    end=e,
                    text=m.group(1),
                    kind="PHONE_URL",
                    verified=m.group(1) in ALLOWED_PHONE_DIGITS,
                )
            )
    return sorted(out, key=lambda v: v.start)


# --- refund promises ----------------------------------------------------------------------------------------------------


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    start = 0
    for m in _SENTENCE_END.finditer(text, 0, pos):
        start = m.end()
    nxt = _SENTENCE_END.search(text, pos)
    return start, nxt.start() if nxt else len(text)


def _negated(text: str, pos: int) -> bool:
    """True when a negation directly governs the verb at `pos` (same sentence, only auxiliaries in between)."""
    start, _ = _sentence_bounds(text, pos)
    return _NEGATED_TAIL.search(text[start:pos]) is not None


def _date_forms(d: date) -> list[str]:
    forms = [d.isoformat(), f"{d.day}/{d.month}/{d.year}", f"{d.day:02d}/{d.month:02d}/{d.year}"]
    for months in (_en.MONTHS, _ms.MONTHS):
        forms += [f"{d.day} {months[d.month - 1].lower()}", f"{d.day:02d} {months[d.month - 1].lower()}"]
    return forms


def _cites_reversal(sentence: str, facts: FactSheet) -> bool:
    low = sentence.lower()
    rev_id = facts.ids.get("reversal")
    if rev_id and rev_id.lower() in low:
        return True
    rev_date = facts.dates.get("reversal")
    if rev_date and any(f in low for f in _date_forms(rev_date)):
        return True
    return _REVERSAL_WORDS.search(sentence) is not None


def _refund_promises(text: str, facts: FactSheet) -> list[str]:
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    for rx in _REFUND_RES:
        for m in rx.finditer(text):
            if not _negated(text, m.start()):
                found.append(m.group())
                spans.append(m.span())
    factual_ok = facts.outcome == "DECLINE" and "reversal" in facts.ids
    for rx in _FACTUAL_RES:
        for m in rx.finditer(text):
            if any(s <= m.start() and m.end() <= e for s, e in spans) or _negated(text, m.start()):
                continue
            if factual_ok:
                lo, hi = _sentence_bounds(text, m.start())
                if not _FUTURE_TAIL.search(text[lo : m.start()]) and _cites_reversal(text[lo:hi], facts):
                    continue
            found.append(m.group())
            spans.append(m.span())
    return found


def check_reply(text: str, facts: FactSheet) -> CheckResult:
    issues: list[CheckIssue] = []
    verdicts = token_verdicts(text, facts)

    # 1-2 + 5(phone/url): unverified ids, amounts, phone numbers, URLs
    for v in verdicts:
        if v.verified:
            continue
        if v.kind == "TXN_ID":
            issues.append(
                CheckIssue(
                    code="TXN_ID",
                    message=f"transaction {v.text} is not in this case's evidence",
                    token=v.text,
                )
            )
        elif v.kind == "AMOUNT":
            shown = f"RM{v.value:.2f}" if v.value is not None else v.text
            issues.append(
                CheckIssue(
                    code="AMOUNT", message=f"amount {shown} is not in this case's evidence", token=v.text
                )
            )
        else:
            issues.append(
                CheckIssue(
                    code="PHONE_URL", message=f"{v.text} is not in the verified contact list", token=v.text
                )
            )

    # 3: outcome consistency
    if facts.outcome != "REFUND":
        for verb in _refund_promises(text, facts):
            issues.append(
                CheckIssue(
                    code="OUTCOME",
                    message=f"refund promise '{verb}' but the outcome is {facts.outcome}",
                    token=verb,
                )
            )
    else:
        mentioned = [v.value for v in verdicts if v.kind == "AMOUNT"]
        if not any(a is not None and abs(a - facts.refund_myr) <= AMOUNT_TOLERANCE for a in mentioned):
            issues.append(
                CheckIssue(
                    code="OUTCOME",
                    message=f"refund amount RM{facts.refund_myr:.2f} is missing from the reply",
                )
            )

    # 4: language. MIXED is accepted only when the reply language clearly dominates; empty / very short text can't be judged.
    found = lang.detect(text)
    if found == "OTHER" or (found in ("EN", "MS") and found != facts.language):
        issues.append(
            CheckIssue(
                code="LANGUAGE", message=f"reply reads as {found} but the reply language is {facts.language}"
            )
        )
    elif found == "MIXED":
        en, ms, _ = lang.counts(text)
        if en + ms >= lang.MIN_HITS and lang.dominant(text) != facts.language:
            issues.append(
                CheckIssue(code="LANGUAGE", message=f"reply is mixed and mostly not {facts.language}")
            )
        elif en + ms >= lang.MIN_HITS:
            own, other = (en, ms) if facts.language == "EN" else (ms, en)
            if other / (own + other) > MIXED_MAX_OTHER_SHARE:
                issues.append(
                    CheckIssue(code="LANGUAGE", message=f"reply mixes in too much non-{facts.language} text")
                )

    # 5: hygiene
    for rx in _JARGON_RES:
        for m in rx.finditer(text):
            issues.append(
                CheckIssue(
                    code="HYGIENE",
                    message=f"internal term '{m.group()}' in a customer reply",
                    token=m.group(),
                )
            )
    for rx in _PLACEHOLDER_RES:
        for m in rx.finditer(text):
            issues.append(
                CheckIssue(code="HYGIENE", message=f"unfilled placeholder '{m.group()}'", token=m.group())
            )
    if len(text) > MAX_REPLY_CHARS:
        issues.append(
            CheckIssue(
                code="HYGIENE", message=f"reply is {len(text)} characters, the limit is {MAX_REPLY_CHARS}"
            )
        )
    words = len(text.split())
    if words < config.REPLY_MIN_WORDS and facts.ids.get("state") != "wrong_customer":
        issues.append(
            CheckIssue(
                code="HYGIENE",
                message=f"reply has {words} words, too short to be a reply (minimum {config.REPLY_MIN_WORDS})",
            )
        )

    return CheckResult(ok=not issues, issues=issues)
