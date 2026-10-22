"""Orchestrates the Core stage functions (SPEC §3). Holds no rules; I/O lives in db.py and api/."""

import time
from collections.abc import Callable
from typing import TypeVar

from teratai import classify, dates, match, policy, reply
from teratai.models import AgentDecision, ComplaintRow, Emit, Mode, StageEvent

T = TypeVar("T")


def _noop(_: StageEvent) -> None:
    return None


def _timed(emit: Emit, stage: str, fn: Callable[[], T]) -> T:
    t0 = time.perf_counter()
    out = fn()
    emit(StageEvent(stage=stage, ok=True, latency_ms=int((time.perf_counter() - t0) * 1000), payload={}))
    return out


def process_complaint(row: ComplaintRow, run_id: str, emit: Emit | None = None) -> AgentDecision:
    """Run one complaint through every stage. Pure: no DB writes (see store)."""
    emit = emit or _noop
    mode: Mode = "live" if run_id == "live" else "batch"
    u = classify.understand(row, mode, emit)
    issue = u.issues[0]
    window = _timed(emit, "resolve", lambda: dates.resolve_window(issue.date_phrase, row.received_at))
    m = match.match_case(row, u, window, emit)
    d = _timed(emit, "decide", lambda: policy.decide(row, issue.category, m))
    facts = reply.build_facts(row, issue.category, m, d)
    r = reply.write_reply(facts, mode, emit)
    flags = [
        f
        for f, on in (("injection_suspected", u.injection_suspected), ("check_flagged", not r.check.ok))
        if on
    ]
    return AgentDecision(
        complaint_id=row.complaint_id or "",
        run_id=run_id,
        customer_id=row.customer_id,
        category=issue.category,
        category_conf=u.top3[0][1] if u.top3 else 0.0,
        matched_txn_id=m.txn_id or "",
        outcome=d.outcome,
        refund_amount_myr=d.refund_myr,
        priority=d.priority,
        reply_language=facts.language,
        route=d.route,
        reply_text=r.text,
        check_ok=r.check.ok,
        flags=flags,
        understanding=u,
        match=m,
        decision=d,
        facts=facts,
        reply=r,
    )


def store(row: ComplaintRow, decision: AgentDecision) -> int:
    """Write-back (SPEC §4.8): case row, status, queue, assignment. P4a stub: no-op; P1/P7 replace it."""
    return 0
