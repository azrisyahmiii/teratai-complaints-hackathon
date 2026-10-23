"""Deterministic reply templates: category x outcome x language (SPEC §4.6 fallback; always passes the self-check).

`render(facts)` picks a template key from the fact sheet alone, fills it and returns the text. Adding a template is one
dict entry in `en.py` and `ms.py` (same key) plus, for a new variant, one line in `template_key`.
"""

from datetime import date
from decimal import Decimal
from types import ModuleType

from teratai import config
from teratai.models import FactSheet
from teratai.templates import en, ms

_LANGS: dict[str, ModuleType] = {"EN": en, "MS": ms}
_AT = {"EN": " at {}", "MS": " di {}"}
_TO = {"EN": " to {}", "MS": " kepada {}"}
_DATE_KEYS = {
    "txn": "date",
    "reversal": "rev_date",
    "sibling": "sibling_date",
}  # FactSheet.dates key -> placeholder
_AMOUNT_KEYS = {"txn": "amount"}  # every other FactSheet.amounts key is its own placeholder


def state_of(facts: FactSheet) -> str:
    """decided | needs_info | wrong_customer | not_complaint (reserved key `ids["state"]`, see reply.build_facts)."""
    return facts.ids.get("state", "decided")


def template_key(facts: FactSheet) -> str:
    state = state_of(facts)
    if state == "wrong_customer":
        return "WRONG_CUSTOMER"
    if state == "needs_info":
        return "NEEDS_INFO.SCAM" if facts.category == "SCAM_TRANSFER" else "NEEDS_INFO"
    if state == "not_complaint":
        return "NOT_COMPLAINT"
    base = f"{facts.category}.{facts.outcome}"
    if facts.category == "DUPLICATE_CHARGE" and facts.outcome == "DECLINE":
        return base + (
            ".reversed" if "reversal" in facts.ids else ".apart" if "sibling" in facts.ids else ".single"
        )
    if facts.category == "FAILED_TRANSFER" and facts.outcome == "DECLINE":
        return base + (".reversed" if "reversal" in facts.ids else ".completed")
    if (
        facts.category == "FEE_DISPUTE"
        and facts.outcome == "REFUND"
        and facts.amounts.get("due", Decimal(1)) == 0
    ):
        return base + ".waived"
    return base


def money(x: Decimal) -> str:
    return f"RM{x:,.2f}"


def fmt_date(d: date, language: str) -> str:
    return f"{d.day} {_LANGS[language].MONTHS[d.month - 1]} {d.year}"


def who(facts: FactSheet) -> str:
    return " ".join(p for p in (facts.honorific, facts.customer_name) if p)


def context(facts: FactSheet) -> dict[str, str]:
    """Every placeholder a template may use. Keys with no data are absent (the template then falls back to GENERIC)."""
    lg = facts.language
    mod = _LANGS[lg]
    ctx: dict[str, str] = {
        "who": who(facts),
        "refund": money(facts.refund_myr),
        "sla_days": str(facts.sla_days),
        "update_days": str(config.SCAM_UPDATE_WORKING_DAYS),
        "redress": mod.REDRESS,
        "scam_help": mod.SCAM_HELP,
        "at": "",
        "to": "",
    }
    merchant = facts.ids.get("merchant", "")
    if merchant:
        ctx["at"], ctx["to"] = _AT[lg].format(merchant), _TO[lg].format(merchant)
    if "txn" in facts.ids:
        ctx["txn"] = facts.ids["txn"]
    for key, value in facts.amounts.items():
        ctx[_AMOUNT_KEYS.get(key, key)] = money(value)
    for key, day in facts.dates.items():
        ctx[_DATE_KEYS.get(key, f"{key}_date")] = fmt_date(day, lg)
    return ctx


def render_key(facts: FactSheet, key: str) -> str:
    """Fill the template `key`; if a fact it needs is missing, fall back to the GENERIC text (promises nothing)."""
    texts = _LANGS[facts.language].TEXTS
    ctx = context(facts)
    try:
        return texts[key].format(**ctx)
    except KeyError:
        return texts["GENERIC"].format(**ctx)


def render(facts: FactSheet) -> str:
    """The deterministic reply text; never empty. `wrong_customer` gets a verification reply that names no
    transaction, amount or payee (nothing about another customer's data)."""
    return render_key(facts, template_key(facts))
