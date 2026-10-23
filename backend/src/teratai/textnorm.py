"""Clue-only text normaliser (robustness review §5.1.5). Pure, no I/O.

`normalise(text)` rewrites established SMS-Malay / Manglish short forms to the words the date parser and the
language counter know ("lps" -> "lepas", "smlm" -> "semalam", "abt" -> "about"). It is used ONLY to read clues
(dates, language). The stored complaint text is never altered, and every verbatim-span check runs against the
original text, so a normalised word can never end up in a reply or in a money value.

The table is a class of well-known forms, not a list of the reviewers' strings. Add a form here, with a test row.
"""

import re

# short form -> expansion. Keys are whole tokens (case-insensitive). Only forms that are unambiguous in a
# banking complaint belong here ("x" alone is "tak"; "sat"/"sun" are NOT here, the date grammar owns weekdays).
_FORMS: dict[str, str] = {
    # negation, pronouns, particles
    "x": "tak", "tk": "tak", "xde": "tiada", "xda": "tiada", "sy": "saya", "sya": "saya", "sy2": "saya",
    "yg": "yang", "dgn": "dengan", "ngn": "dengan", "utk": "untuk", "untk": "untuk", "tp": "tapi", "tpi": "tapi",
    "dh": "dah", "dah": "dah", "jgk": "juga", "jg": "juga", "je": "je", "jek": "je", "sj": "saja", "shj": "sahaja",
    "kt": "di", "kat": "di", "pd": "pada", "dlm": "dalam", "ke": "ke", "kpd": "kepada",
    "blh": "boleh", "xboleh": "tak boleh", "tlg": "tolong", "mnta": "minta", "mntk": "minta", "cpt": "cepat",
    "skrg": "sekarang", "sgt": "sangat", "sgt2": "sangat", "knp": "kenapa", "mcm": "macam", "lg": "lagi",
    "org": "orang", "byr": "bayar", "bkn": "bukan", "bukn": "bukan", "ni": "ini", "tu": "itu", "trus": "terus",
    "tq": "terima kasih", "tqvm": "terima kasih", "tx": "terima kasih", "kuar": "keluar", "kluar": "keluar",
    "lbh": "lebih", "krg": "kurang", "kurg": "kurang", "kira2": "kira-kira", "hjg": "hujung", "hjng": "hujung",
    "smpai": "sampai", "sampe": "sampai", "mgu": "minggu", "mgg": "minggu", "mggu": "minggu", "hr": "hari",
    # time words
    "lps": "lepas", "lpas": "lepas", "lepaz": "lepas", "smlm": "semalam", "semlm": "semalam", "kmrn": "kelmarin",
    "kmarin": "kelmarin", "td": "tadi", "tadi": "tadi", "jmt": "jumaat", "jmaat": "jumaat", "slasa": "selasa",
    "isnin": "isnin", "khamis": "khamis", "ytd": "yesterday", "yday": "yesterday", "ystd": "yesterday",
    "tmr": "tomorrow", "lst": "last", "abt": "about", "approx": "approx", "ard": "around", "apprx": "approx",
    "pls": "please", "plz": "please", "thx": "thanks", "tks": "thanks", "wk": "week", "wks": "weeks",
    "mth": "month", "mths": "months",
}  # fmt: skip

_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
_DIGIT_LETTER = re.compile(r"(?<=\d)(?=(?:hb|hari|days?|weeks?|minggu)\b)", re.IGNORECASE)
# "15hb" -> "15 hb", "2days" -> "2 days": a number glued to its unit word.


def normalise(text: str) -> str:
    """Clue-only rewrite of SMS short forms. Case is kept for unknown tokens; known forms come out lower-case."""
    spaced = _DIGIT_LETTER.sub(" ", text)

    def sub(m: re.Match[str]) -> str:
        tok = m.group(0)
        return _FORMS.get(tok.lower(), tok)

    out = _TOKEN.sub(sub, spaced)
    return re.sub(r"\blebih\s+kurang\b", "lebih kurang", out, flags=re.IGNORECASE)
