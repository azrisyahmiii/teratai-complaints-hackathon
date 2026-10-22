"""EN / MS language detector and reply-language rule (SPEC §4.2 "Language (code)").

Policy (`policy_parameters.csv` REPLY_LANGUAGE): reply in the language the complaint is written in. If it mixes
both, if it is a call-centre note written by staff, or if it is neither (e.g. Chinese, Tamil), use the customer's
`preferred_language`.

`detect` is a stopword-ratio detector over function words only (they carry no domain meaning, so the same
lists work for complaints and for generated replies). C7's self-check reuses `detect` / `dominant` on replies.
"""

import re
from typing import Literal

from teratai import data
from teratai.models import ComplaintRow, Lang

Detected = Literal["EN", "MS", "MIXED", "OTHER"]

# Function words. Words that are common in the other language's text (e.g. "hari", "bulan", "ada") are fine in MS
# only; words that Malay chat borrows from English ("please", "thanks", "ok") are left out of EN.
EN_WORDS = frozenset(
    ["the", "an", "is", "are", "was", "were", "be", "been", "am", "i", "my", "me", "mine", "we", "our", "you", "your", "it", "its", "this", "that", "these", "those", "there", "to", "of", "in", "on", "at", "for", "from", "by", "with", "without", "about", "after", "before", "during", "and", "or", "but", "so", "if", "as", "than", "then", "not", "no", "never", "nobody", "nothing", "did", "do", "does", "done", "doing", "have", "has", "had", "having", "will", "would", "can", "could", "should", "may", "might", "what", "which", "who", "why", "how", "when", "where", "still", "again", "twice", "also", "just", "only", "very", "much", "too", "more", "any", "some", "all", "each", "both", "same", "he", "she", "they", "them", "his", "her", "their", "customer", "says", "said", "reports", "claims", "wants", "hello", "hi", "dear", "please", "pls", "thank", "thanks", "regards", "sincerely", "asap", "because", "since", "while", "until", "over", "under", "into", "out", "up", "down", "off", "charged", "charge", "debited", "deducted", "received", "sent", "paid", "pay", "money", "cash", "card", "account", "transfer", "refund", "check", "appears", "appear", "showed", "shows", "show", "tried", "try", "asked", "ask", "told", "tell", "service", "fee", "annual", "monthly", "withdraw", "withdrew", "withdrawal", "transaction", "payment", "call", "called", "hotline", "app", "last", "next", "week", "yesterday", "today", "tonight", "morning", "staff", "rude", "group", "scam", "repair", "logout"]
)
MS_WORDS = frozenset(
    ["saya", "aku", "kami", "kita", "anda", "kamu", "dia", "mereka", "dan", "atau", "tetapi", "tapi", "dengan", "untuk", "kepada", "daripada", "dari", "ke", "di", "pada", "dalam", "oleh", "bagi", "antara", "yang", "ini", "itu", "ada", "tidak", "tak", "bukan", "belum", "sudah", "telah", "dah", "lagi", "masih", "pun", "juga", "sahaja", "saja", "je", "lah", "kah", "ni", "akan", "mahu", "nak", "boleh", "dapat", "perlu", "harus", "mesti", "apa", "kenapa", "mengapa", "bila", "bagaimana", "siapa", "mana", "hari", "semalam", "kelmarin", "esok", "tadi", "lepas", "minggu", "bulan", "tahun", "kali", "dua", "tiga", "empat", "lima", "sekali", "mohon", "sila", "harap", "tolong", "bantu", "semak", "pulangkan", "kembalikan", "selesaikan", "wang", "duit", "akaun", "kad", "caj", "dicaj", "dikenakan", "ditolak", "kena", "potong", "tolak", "kat", "guna", "buat", "orang", "sebanyak", "lebih", "kurang", "kira", "sangat", "amat", "terlalu", "terima", "kasih", "sekian", "tuan", "puan", "encik", "cik", "assalamualaikum", "salam", "dukacita", "dimaklumkan", "pihak", "tiada", "langsung", "hanya", "cuma", "sebab", "kerana", "kalau", "jika", "supaya", "agar", "gagal", "berjaya", "masuk", "keluar", "ya", "pelanggan", "menyatakan", "menghubungi", "melaporkan", "mendakwa"]
)

# --- thresholds (tuned against `reply_language` in labels_train.csv; see tests) -------------------------------
MIN_HITS = 2  # fewer stopword hits than this in total -> not enough evidence, MIXED
MINORITY_SHARE = 0.05  # a language is "present" when it holds at least this share of the stopword hits
NON_LATIN_SHARE = 0.30  # share of non-Latin letters above which the text is OTHER

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def counts(text: str) -> tuple[int, int, int]:
    """(EN stopword hits, MS stopword hits, token count) over the alphabetic tokens of `text`."""
    toks = _tokens(text)
    return sum(t in EN_WORDS for t in toks), sum(t in MS_WORDS for t in toks), len(toks)


def detect(text: str) -> Detected:
    """EN or MS when one language clearly dominates, MIXED when both show, OTHER for non-Latin scripts."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(ord(c) > 0x24F for c in letters) / len(letters) >= NON_LATIN_SHARE:
        return "OTHER"
    en, ms, _ = counts(text)
    if en + ms < MIN_HITS:
        return "MIXED"
    ms_share = ms / (en + ms)
    if ms_share <= MINORITY_SHARE:
        return "EN"
    if ms_share >= 1 - MINORITY_SHARE:
        return "MS"
    return "MIXED"


def dominant(text: str) -> Lang:
    """EN or MS by the larger stopword ratio (ties -> EN). For generated replies, which are never mixed."""
    en, ms, _ = counts(text)
    return "MS" if ms > en else "EN"


def reply_language(row: ComplaintRow) -> tuple[Lang, str]:
    """The language to reply in, with the reason shown in the trace."""
    pref: Lang = "MS" if data.customer(row.customer_id).preferred_language == "MS" else "EN"
    if row.channel == "Call centre note":
        return pref, f"call-centre note written by staff -> preferred_language {pref}"
    found = detect(f"{row.subject} {row.text}")
    en, ms, _ = counts(f"{row.subject} {row.text}")
    stats = f"EN {en} / MS {ms} stopword hits"
    if found == "EN" or found == "MS":
        return found, f"written in {found} ({stats})"
    return pref, f"{found.lower()} language ({stats}) -> preferred_language {pref}"
