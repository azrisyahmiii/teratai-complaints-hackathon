"""Understand stage (SPEC §4.2). P4a stub: returns the CMP-00165 gold answer; C4/C5 replace it."""

from decimal import Decimal

from teratai.models import ComplaintRow, Emit, Issue, Mode, StageEvent, Understanding


def understand(row: ComplaintRow, mode: Mode, emit: Emit) -> Understanding:
    u = Understanding(
        issues=[
            Issue(
                category="DUPLICATE_CHARGE",
                amount=Decimal("46.66"),
                counterparty="GoRide",
                date_phrase="hari Selasa lepas",
            )
        ],
        top3=[("DUPLICATE_CHARGE", 1.0)],
        source="classifier",
        language="MS",
        language_reason="stub",
        is_complaint=True,
        injection_suspected=False,
        scam_cue=False,
    )
    emit(StageEvent(stage="understand", ok=True, latency_ms=0, payload={"stub": True}))
    return u
