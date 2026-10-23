"""Orchestrates the Core stage functions (SPEC §3). Holds no rules; I/O lives in db.py and api/."""

import json
import time
from collections.abc import Callable
from typing import TypeVar

from teratai import classify, dates, db, match, policy, reply
from teratai.api import states
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
    facts = reply.build_facts(row, issue.category, m, d, u.is_complaint)
    last_reply: dict[str, object] = {}

    def capture(ev: StageEvent) -> None:
        if ev.stage == "reply":
            last_reply.clear()
            last_reply.update(ev.payload)
        emit(ev)

    r = reply.write_reply(facts, mode, capture)
    flags = sorted(
        f
        for f, on in (
            ("injection_suspected", u.injection_suspected),
            ("check_flagged", (not r.check.ok) or bool(last_reply.get("check_flagged"))),
            ("degraded", bool(last_reply.get("degraded"))),
            ("not_complaint", bool(last_reply.get("not_complaint"))),
            ("wrong_customer", m.status == "WRONG_CUSTOMER"),
            ("needs_info", d.needs_info),
            ("vulnerable", d.inputs.get("vulnerable_bump") == "yes"),
        )
        if on
    )
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
    """Write-back, idempotent by (run_id, complaint_id). Never overwrites a human action."""
    state, sent = states.initial_state(decision.route)
    t = db.now()
    cid = decision.complaint_id
    with db.connect() as con:
        con.execute(
            "INSERT INTO cases(complaint_id, run_id, row, status, agent_decision, flags, case_state, sent,"
            " created_at, updated_at) VALUES(?,?,?,'done',?,?,?,?,?,?) "
            "ON CONFLICT(run_id, complaint_id) DO UPDATE SET status='done', error=NULL,"
            " row=excluded.row, agent_decision=excluded.agent_decision, flags=excluded.flags,"
            " case_state=CASE WHEN human_action IS NULL THEN excluded.case_state ELSE case_state END,"
            " sent=CASE WHEN human_action IS NULL THEN excluded.sent ELSE sent END,"
            " updated_at=excluded.updated_at",
            (cid, decision.run_id, row.model_dump_json(), decision.model_dump_json(),
             json.dumps(decision.flags), state, int(sent), t, t),
        )
        if sent:
            have = con.execute(
                "SELECT 1 FROM outbox WHERE run_id=? AND complaint_id=?", (decision.run_id, cid)
            ).fetchone()
            if have is None:
                con.execute(
                    "INSERT INTO outbox(run_id, complaint_id, ts, language, text, authorised_by)"
                    " VALUES(?,?,?,?,?,'agent')",
                    (decision.run_id, cid, t, decision.reply_language, decision.reply_text),
                )
    return 0
