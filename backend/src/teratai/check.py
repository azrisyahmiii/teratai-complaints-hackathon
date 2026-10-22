"""Decision-bound self-check (SPEC §4.7, checks 1-5). Pure: text + FactSheet in, CheckResult out.

Only facts of THIS case are allowed in a reply: the ids and amounts on the `FactSheet` (plus the auto-refund limit and the
verified regulatory contacts below), never the customer's whole history. That is stricter than `starter/check_reply.py`.

Every list below (refund verbs, jargon, allow-lists) is data: a new entry is a new line, not a code change.
`token_verdicts` is the single source of truth: `check_reply` turns its unverified spans into issues, and the UI
uses the same spans to paint tokens green (verified) or red (not in evidence), SPEC §13.5.
"""

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from teratai import config, lang
from teratai.models import CheckIssue, CheckResult, FactSheet

# --- verified regulatory facts (web-checked 2026-10-22; BA to re-confirm in eval/regulatory_facts.md) ------------
# NSRC hotline 997:  https://www.bnm.gov.my/faqs/scams and https://nfcc.jpm.gov.my/index.php/en/about-nsrc
# FMOS (formerly OFS, renamed 6 Sep 2024, launched 17 Jan 2025): https://www.fmos.org.my/en/who-we-are/
# BNMLINK (formerly BNMTELELINK, renamed July 2023), 1-300-88-5465: https://www.bnm.gov.my/-/bnmlink-services-remain-available
ALLOWED_PHONE_DIGITS: frozenset[str] = frozenset({"997", "1300885465"})
ALLOWED_URL_HOSTS: frozenset[str] = frozenset({"fmos.org.my", "bnm.gov.my"})

MAX_REPLY_CHARS = 1200
MIXED_MAX_OTHER_SHARE = (
    0.20  # a MIXED reply passes only if at most 20% of its stopword hits are the other language
)
AMOUNT_TOLERANCE = Decimal("0.005")
# Words with these in the 25 characters before a refund verb make it a refusal ("we cannot refund"), which is fine.
_NEGATIONS = re.compile(
    r"\b(?:no|not|cannot|can't|unable|never|without|tidak|tak|belum|bukan)\b", re.IGNORECASE
)

_TXN = re.compile(r"TXN-\d{7}")
_AMOUNT_NUM = r"[\d,]+(?:\.\d{1,2})?"
_AMOUNT = re.compile(
    rf"(?<![A-Za-z])(?:RM|MYR)\s?(?P<a>{_AMOUNT_NUM})|(?P<b>{_AMOUNT_NUM})\s?(?:ringgit)\b", re.IGNORECASE
)

# Refund promises, EN + MS. Forbidden unless the outcome is REFUND.
REFUND_VERBS: tuple[str, ...] = (
    r"\brefunded\b",
    r"\b(?:will|shall)\s+(?:be\s+)?refund(?:ed)?\b",
    r"\bwe\s+refund\b",
    r"\b(?:will\s+be|has\s+been|have\s+been|is\s+being)\s+credited\b",
    r"\bcredited\s+back\b",
    r"\bdikreditkan\b",
    r"\bdikembalikan\b",
    r"\bdibayar\s+balik\b",
    r"\bbayaran\s+balik\b",
)
_REFUND_RES = [re.compile(p, re.IGNORECASE) for p in REFUND_VERBS]

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

# phone numbers: 7+ digits with the usual separators, or a 3-5 digit short code right after "call", "hubungi", ...
_PHONE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().\-]{5,}\d(?!\w)")
_SHORT_CODE = re.compile(
    r"\b(?:call|dial|phone|hotline|whatsapp|sms|hubungi|telefon|talian|dail)\b\W+(?:[A-Za-z]+\W+){0,3}?(\d{3,5})\b",
    re.IGNORECASE,
)
_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_URL = re.compile(
    r"(?:https?://|www\.)[^\s,;)]+"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|my|org|net|gov|edu|io|co)\b(?:/[^\s,;)]*)?",
    re.IGNORECASE,
)


class TokenVerdict(BaseModel):
    """One checked token with its position in the text, for green / red highlighting."""

    start: int
    end: int
    text: str
    kind: Literal["TXN_ID", "AMOUNT", "PHONE_URL"]
    verified: bool


def _value_of(token: str) -> Decimal | None:
    m = _AMOUNT.fullmatch(token)
    return _amount_value(m) if m else None


def _allowed_ids(facts: FactSheet) -> set[str]:
    return {v for v in facts.ids.values() if _TXN.fullmatch(v)}


def _allowed_amounts(facts: FactSheet) -> set[Decimal]:
    return {*facts.amounts.values(), facts.refund_myr, config.AUTO_REFUND_LIMIT_MYR}


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        chars[s:e] = " " * (e - s)
    return "".join(chars)


def _host(url: str) -> str:
    host = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).split("/")[0]
    return host.rstrip(".")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _amount_value(m: re.Match[str]) -> Decimal | None:
    raw = (m.group("a") or m.group("b") or "").strip(",")
    try:
        return Decimal(raw.replace(",", ""))
    except ArithmeticError:
        return None


def token_verdicts(text: str, facts: FactSheet) -> list[TokenVerdict]:
    """Every transaction id, money amount, phone number and URL in `text`, each marked verified or not."""
    out: list[TokenVerdict] = []
    ids, amounts = _allowed_ids(facts), _allowed_amounts(facts)
    taken: list[tuple[int, int]] = []
    for m in _TXN.finditer(text):
        out.append(
            TokenVerdict(
                start=m.start(), end=m.end(), text=m.group(), kind="TXN_ID", verified=m.group() in ids
            )
        )
        taken.append(m.span())
    for m in _AMOUNT.finditer(text):
        value = _amount_value(m)
        ok = value is not None and any(abs(value - a) <= AMOUNT_TOLERANCE for a in amounts)
        out.append(TokenVerdict(start=m.start(), end=m.end(), text=m.group(), kind="AMOUNT", verified=ok))
        taken.append(m.span())
    for m in _URL.finditer(text):
        host = _host(m.group())
        ok = any(host == h or host.endswith("." + h) for h in ALLOWED_URL_HOSTS)
        out.append(TokenVerdict(start=m.start(), end=m.end(), text=m.group(), kind="PHONE_URL", verified=ok))
        taken.append(m.span())
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


def _refund_promises(text: str) -> list[str]:
    found: list[str] = []
    for rx in _REFUND_RES:
        for m in rx.finditer(text):
            if not _NEGATIONS.search(text[max(0, m.start() - 25) : m.start()]):
                found.append(m.group())
    return found


def check_reply(text: str, facts: FactSheet) -> CheckResult:
    issues: list[CheckIssue] = []

    # 1-2 + 5(phone/url): unverified ids, amounts, phone numbers, URLs
    for v in token_verdicts(text, facts):
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
            value = _value_of(v.text)
            shown = f"RM{value:.2f}" if value is not None else v.text
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
        for verb in _refund_promises(text):
            issues.append(
                CheckIssue(
                    code="OUTCOME",
                    message=f"refund promise '{verb}' but the outcome is {facts.outcome}",
                    token=verb,
                )
            )
    else:
        mentioned = [_value_of(v.text) for v in token_verdicts(text, facts) if v.kind == "AMOUNT"]
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

    return CheckResult(ok=not issues, issues=issues)
