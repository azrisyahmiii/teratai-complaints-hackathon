"""Read API for our web UI (queues, case page, outbox). Writes go through the organisers' /cases/{id}/actions."""

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from teratai import check, data, db, settings
from teratai.api import states
from teratai.api.routes_agent import money
from teratai.check import TokenVerdict
from teratai.models import AgentDecision, CheckIssue, ComplaintRow, FactSheet

router = APIRouter(prefix="/api")

PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}


class CaseRow(BaseModel):
    complaint_id: str
    status: Literal["processing", "done", "error"]
    customer_id: str
    customer_name: str
    channel: str
    received_at: datetime
    category: str | None = None
    priority: str | None = None
    outcome: str | None = None
    route: str | None = None
    refund_amount_myr: str | None = None
    disputed_amount_myr: str | None = None  # the matched transaction's amount
    reply_language: str | None = None
    case_state: str | None = None
    sent: bool = False
    self_check: Literal["passed", "flagged"] | None = None
    ack_due: datetime | None = None
    flags: list[str] = []


class Oldest(BaseModel):
    complaint_id: str
    received_at: datetime


class OfficerFigures(BaseModel):
    waiting: int
    p1_waiting: int
    ack_due_2h: int
    check_flagged: int
    oldest: Oldest | None


class FraudFigures(BaseModel):
    open: int
    p1_open: int
    ack_overdue: int
    amount_disputed_myr: str


class ManagerFigures(BaseModel):
    all: int
    awaiting_approval: int
    with_fraud_team: int
    auto_resolved: int
    processing: int
    errors: int


class Figures(BaseModel):
    now: datetime
    officer: OfficerFigures
    fraud: FraudFigures
    manager: ManagerFigures


class CaseList(BaseModel):
    items: list[CaseRow]
    counts: dict[str, int]
    figures: Figures


EvidenceRole = Literal["matched", "candidate", "duplicate_sibling", "reversal"]


class EvidenceRow(BaseModel):
    txn_id: str
    role: EvidenceRole
    txn_time: datetime
    amount_myr: str
    channel: str
    merchant: str
    status: str
    auth_method: str
    description: str
    score: int | None = None
    score_breakdown: dict[str, int] = {}


class AtmJournalView(BaseModel):
    txn_id: str
    atm_location: str
    requested_myr: str
    dispensed_myr: str
    journal_status: str


class EventView(BaseModel):
    ts: str
    actor: str
    action: str | None
    stage: str | None
    model: str | None
    latency_ms: int
    cost_usd: str
    ok: bool
    payload: dict[str, Any]


class OutboxItem(BaseModel):
    id: int
    complaint_id: str
    customer_name: str
    ts: str
    language: str
    text: str
    authorised_by: str


class CaseDetail(BaseModel):
    case: CaseRow
    subject: str
    text: str
    error: str | None = None
    customer_preferred_language: str | None = None
    human_action: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None  # outcome, refund, route, rule, calc, inputs
    understanding: dict[str, Any] | None = None  # source, top3, clues, language reason, injection
    window: dict[str, Any] | None = None
    match_status: str | None = None
    evidence: list[EvidenceRow] = []
    atm_journal: AtmJournalView | None = None
    reply_text: str = ""
    reply_source: str | None = None
    reply_drafts: int = 0
    check_issues: list[CheckIssue] = []
    tokens: list[TokenVerdict] = []
    events: list[EventView] = []
    outbox: list[OutboxItem] = []


class CheckIn(BaseModel):
    text: str


class CheckOut(BaseModel):
    self_check: Literal["passed", "flagged"]
    issues: list[CheckIssue]
    tokens: list[TokenVerdict]


def _name(customer_id: str) -> str:
    return data.customer(customer_id).full_name if data.has_customer(customer_id) else ""


def _ack_due(received_at: datetime, priority: str) -> datetime:
    return received_at + timedelta(hours=data.sla_policy()[priority].ack_hours)


def _row(r: sqlite3.Row) -> tuple[CaseRow, AgentDecision | None]:
    complaint = ComplaintRow.model_validate_json(r["row"])
    out = CaseRow(
        complaint_id=r["complaint_id"],
        status=r["status"],
        customer_id=complaint.customer_id,
        customer_name=_name(complaint.customer_id),
        channel=complaint.channel,
        received_at=complaint.received_at,
    )
    if r["status"] != "done":
        return out, None
    ad = AgentDecision.model_validate_json(r["agent_decision"])
    disputed = data.txn(ad.matched_txn_id).amount if ad.matched_txn_id and data.has_txn(ad.matched_txn_id) else None
    out = out.model_copy(
        update={
            "category": ad.category,
            "priority": ad.priority,
            "outcome": ad.outcome,
            "route": ad.route,
            "refund_amount_myr": money(str(ad.refund_amount_myr)),
            "disputed_amount_myr": money(str(disputed)) if disputed is not None else None,
            "reply_language": ad.reply_language,
            "case_state": r["case_state"],
            "sent": bool(r["sent"]),
            "self_check": "passed" if ad.check_ok else "flagged",
            "ack_due": _ack_due(complaint.received_at, ad.priority),
            "flags": json.loads(r["flags"]) if r["flags"] else [],
        }
    )
    return out, ad


def _sort_key(c: CaseRow) -> tuple[int, datetime]:
    return PRIORITY_ORDER.get(c.priority or "", 3), c.received_at


def _figures(rows: list[CaseRow], now: datetime) -> Figures:
    waiting = [c for c in rows if c.case_state == states.AWAITING]
    fraud = [c for c in rows if c.case_state == states.WITH_FRAUD]
    oldest = min(waiting, key=lambda c: c.received_at, default=None)
    return Figures(
        now=now,
        officer=OfficerFigures(
            waiting=len(waiting),
            p1_waiting=sum(c.priority == "P1" for c in waiting),
            ack_due_2h=sum(c.ack_due is not None and now <= c.ack_due <= now + timedelta(hours=2) for c in waiting),
            check_flagged=sum(c.self_check == "flagged" for c in waiting),
            oldest=Oldest(complaint_id=oldest.complaint_id, received_at=oldest.received_at) if oldest else None,
        ),
        fraud=FraudFigures(
            open=len(fraud),
            p1_open=sum(c.priority == "P1" for c in fraud),
            ack_overdue=sum(c.ack_due is not None and c.ack_due < now for c in fraud),
            amount_disputed_myr=money(str(sum((Decimal(c.disputed_amount_myr or "0") for c in fraud), Decimal(0)))),
        ),
        manager=ManagerFigures(
            all=len(rows),
            awaiting_approval=len(waiting),
            with_fraud_team=len(fraud),
            auto_resolved=sum(c.case_state == states.AUTO_RESOLVED for c in rows),
            processing=sum(c.status == "processing" for c in rows),
            errors=sum(c.status == "error" for c in rows),
        ),
    )


@router.get("/cases")
def list_cases(state: str | None = None, run_id: str = db.LIVE) -> CaseList:
    """Every case in the run, sorted by priority then received time; `state` filters items, never counts or figures."""
    with db.connect() as con:
        rs = con.execute("SELECT * FROM cases WHERE run_id=?", (run_id,)).fetchall()
    rows = sorted((_row(r)[0] for r in rs), key=_sort_key)
    counts = {"all": len(rows)}
    for c in rows:
        key = c.case_state if c.status == "done" else c.status
        counts[key or "unknown"] = counts.get(key or "unknown", 0) + 1
    items = [c for c in rows if state is None or c.case_state == state or c.status == state]
    return CaseList(items=items, counts=counts, figures=_figures(rows, settings.sim_now()))


def _evidence(ad: AgentDecision) -> list[EvidenceRow]:
    out: list[EvidenceRow] = []
    seen: set[str] = set()

    def add(txn_id: str, role: EvidenceRole, score: int | None = None, breakdown: dict[str, int] | None = None) -> None:
        if not txn_id or txn_id in seen or not data.has_txn(txn_id):
            return
        seen.add(txn_id)
        t = data.txn(txn_id)
        out.append(
            EvidenceRow(
                txn_id=t.txn_id, role=role, txn_time=t.txn_time, amount_myr=money(str(t.amount)),
                channel=t.channel, merchant=t.merchant, status=t.status, auth_method=t.auth_method,
                description=t.description, score=score, score_breakdown=breakdown or {},
            )
        )

    scores = {c.txn_id: c for c in ad.match.candidates}
    if ad.matched_txn_id:
        c = scores.get(ad.matched_txn_id)
        add(ad.matched_txn_id, "matched", c.score if c else None, c.breakdown if c else None)
    add(ad.match.related.get("sibling", ""), "duplicate_sibling")
    add(ad.match.related.get("reversal", ""), "reversal")
    for c in sorted(ad.match.candidates, key=lambda c: -c.score):
        add(c.txn_id, "candidate", c.score, c.breakdown)
    return out


def _outbox_items(rs: list[sqlite3.Row], names: dict[str, str]) -> list[OutboxItem]:
    return [
        OutboxItem(
            id=r["id"], complaint_id=r["complaint_id"], customer_name=names.get(r["complaint_id"], ""), ts=r["ts"],
            language=r["language"] or "", text=r["text"] or "", authorised_by=r["authorised_by"] or "",
        )
        for r in rs
    ]


@router.get("/cases/{complaint_id}")
def get_case_detail(complaint_id: str, run_id: str = db.LIVE) -> CaseDetail:
    r = db.get_case(run_id, complaint_id)
    if r is None:
        raise HTTPException(404, detail=f"case {complaint_id} not found")
    row, ad = _row(r)
    complaint = ComplaintRow.model_validate_json(r["row"])
    with db.connect() as con:
        evs = con.execute(
            "SELECT * FROM case_events WHERE run_id=? AND complaint_id=? ORDER BY id", (run_id, complaint_id)
        ).fetchall()
        obx = con.execute(
            "SELECT * FROM outbox WHERE run_id=? AND complaint_id=? ORDER BY id DESC", (run_id, complaint_id)
        ).fetchall()
    events = [
        EventView(
            ts=e["ts"], actor=e["actor"], action=e["action"], stage=e["stage"], model=e["model"],
            latency_ms=e["latency_ms"] or 0, cost_usd=e["cost_usd"] or "0", ok=bool(e["ok"]),
            payload=json.loads(e["payload"]) if e["payload"] else {},
        )
        for e in evs
    ]
    pref = data.customer(complaint.customer_id).preferred_language if data.has_customer(complaint.customer_id) else None
    detail = CaseDetail(
        case=row, subject=complaint.subject, text=complaint.text, error=r["error"],
        customer_preferred_language=pref,
        human_action=json.loads(r["human_action"]) if r["human_action"] else None,
        events=events, outbox=_outbox_items(obx, {complaint_id: row.customer_name}),
    )
    if ad is None:
        return detail
    journal = data.atm_journal(ad.matched_txn_id) if ad.matched_txn_id else None
    return detail.model_copy(
        update={
            "decision": json.loads(ad.decision.model_dump_json()) | {"category_conf": ad.category_conf},
            "understanding": json.loads(ad.understanding.model_dump_json()),
            "window": json.loads(ad.match.window.model_dump_json()),
            "match_status": ad.match.status,
            "evidence": _evidence(ad),
            "atm_journal": AtmJournalView(
                txn_id=journal.txn_id, atm_location=journal.atm_location, requested_myr=money(str(journal.requested)),
                dispensed_myr=money(str(journal.dispensed)), journal_status=journal.journal_status,
            ) if journal else None,
            "reply_text": ad.reply_text,
            "reply_source": ad.reply.source,
            "reply_drafts": len(ad.reply.drafts),
            "check_issues": ad.reply.check.issues,
            "tokens": check.token_verdicts(ad.reply_text, ad.facts),
        }
    )


@router.post("/cases/{complaint_id}/check-reply")
def check_reply(complaint_id: str, body: CheckIn, run_id: str = db.LIVE) -> CheckOut:
    """Dry-run the self-check on an edited reply. Changes nothing; approving still goes through /actions."""
    r = db.get_case(run_id, complaint_id)
    if r is None:
        raise HTTPException(404, detail=f"case {complaint_id} not found")
    if r["status"] != "done":
        raise HTTPException(409, detail=f"case is still {r['status']}")
    facts = FactSheet.model_validate(json.loads(r["agent_decision"])["facts"])
    res = check.check_reply(body.text, facts)
    return CheckOut(
        self_check="passed" if res.ok else "flagged", issues=res.issues, tokens=check.token_verdicts(body.text, facts)
    )


@router.get("/outbox")
def list_outbox(run_id: str = db.LIVE) -> list[OutboxItem]:
    """Simulated replies sent to customers, newest first."""
    with db.connect() as con:
        rs = con.execute("SELECT * FROM outbox WHERE run_id=? ORDER BY id DESC", (run_id,)).fetchall()
        cust = con.execute("SELECT complaint_id, row FROM cases WHERE run_id=?", (run_id,)).fetchall()
    names = {c["complaint_id"]: _name(ComplaintRow.model_validate_json(c["row"]).customer_id) for c in cust}
    return _outbox_items(rs, names)
