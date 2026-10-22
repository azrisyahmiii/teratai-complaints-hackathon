"""Transaction matcher (SPEC §4.4, calls the investigator §4.4b itself).

P4a stub: returns the CMP-00165 gold match; C6 replaces it.
"""

from teratai.models import Candidate, ComplaintRow, DateWindow, Emit, MatchResult, StageEvent, Understanding


def match_case(row: ComplaintRow, u: Understanding, window: DateWindow, emit: Emit) -> MatchResult:
    m = MatchResult(
        status="UNIQUE",
        txn_id="TXN-0115572",
        window=window,
        candidates=[
            Candidate(txn_id="TXN-0115572", score=6, breakdown={"amount": 3, "counterparty": 3}),
        ],
        related={"sibling": "TXN-0115571"},
        source="matcher",
    )
    emit(StageEvent(stage="match", ok=True, latency_ms=0, payload={"stub": True}))
    return m
