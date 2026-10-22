"""Fact sheet + reply writer (SPEC §4.6–4.7). P4a stub: fixed CMP-00165 facts and MS text; C7/C10 replace it."""

from datetime import date
from decimal import Decimal

from teratai.check import check_reply
from teratai.models import (
    Category,
    ComplaintRow,
    Decision,
    Emit,
    FactSheet,
    MatchResult,
    Mode,
    Reply,
    StageEvent,
)


def build_facts(row: ComplaintRow, category: Category, m: MatchResult, d: Decision) -> FactSheet:
    return FactSheet(
        customer_name="Nur Izzati binti Jamal",
        honorific="Puan",
        language="MS",
        category=category,
        outcome=d.outcome,
        refund_myr=d.refund_myr,
        ids={"txn": "TXN-0115572", "sibling": "TXN-0115571"},
        amounts={"txn": Decimal("46.66"), "sibling": Decimal("46.66")},
        dates={"txn": date(2026, 8, 18)},
        sla_days=7,
    )


def write_reply(facts: FactSheet, mode: Mode, emit: Emit) -> Reply:
    text = (
        f"{facts.honorific} {facts.customer_name}, terima kasih kerana menghubungi pihak bank. "
        "Kami telah menyemak caj GoRide pada 18 Ogos 2026 dan mendapati caj TXN-0115572 sebanyak RM46.66 "
        "adalah caj berganda. Jumlah RM46.66 akan dikreditkan semula ke akaun Puan. Sekian, terima kasih."
    )
    check = check_reply(text, facts)
    emit(StageEvent(stage="check", ok=check.ok, latency_ms=0, payload={"stub": True}))
    return Reply(text=text, source="template", check=check, drafts=[text])
