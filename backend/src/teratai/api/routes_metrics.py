"""Read-only, role-scoped insights over stored cases and agent events (docs/dev/tasks/leon-insights.md)."""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from teratai import db, settings
from teratai.api import auth
from teratai.api.auth import User
from teratai.models import Category, Channel

router = APIRouter(prefix="/api")


# --- Contract (leon-insights.md §2). Add fields, never rename. -------------------------------------------------------


class MetricBucket(BaseModel):
    key: str
    count: int
    amount_myr: str | None = None


class MetricRate(BaseModel):
    numerator: int
    denominator: int
    pct: float | None


class MetricDuration(BaseModel):
    count: int
    p50_minutes: float | None
    p95_minutes: float | None


class MetricFilters(BaseModel):
    date_from: date | None
    date_to: date | None
    category: str | None
    channel: str | None


class MetricOptions(BaseModel):
    categories: list[str]
    channels: list[str]
    date_min: date | None
    date_max: date | None


class MetricVolume(BaseModel):
    total: int
    processing: int
    errors: int
    by_day: list[MetricBucket]
    by_channel: list[MetricBucket]
    by_category: list[MetricBucket]
    by_priority: list[MetricBucket]
    by_language: list[MetricBucket]


class MetricOutcomes(BaseModel):
    by_outcome: list[MetricBucket]
    by_route: list[MetricBucket]
    auto_resolve_rate: MetricRate


class MetricMoney(BaseModel):
    refunds_paid_myr: str
    refunds_paid_count: int
    avg_refund_myr: str | None
    awaiting_approval_myr: str
    awaiting_approval_count: int
    refunds_by_category: list[MetricBucket]


class MetricOperations(BaseModel):
    backlog: list[MetricBucket]
    ack_overdue: int
    ack_due_2h: int
    turnaround: MetricDuration
    human_actions: int


class MetricGuardrails(BaseModel):
    self_check_flagged: MetricRate
    reply_source: list[MetricBucket]
    overrides: MetricRate
    rejections: MetricRate
    escalations: MetricRate | None
    injection_suspected: int
    degraded: int
    needs_info: int
    vulnerable: int


class MetricFraud(BaseModel):
    total: int
    open: int
    p1_open: int
    ack_overdue: int
    amount_disputed_myr: str
    by_category: list[MetricBucket]
    acknowledged: int | None
    recall_attempts: int | None
    outcomes: list[MetricBucket] | None


class MetricStage(BaseModel):
    stage: str
    count: int
    p50_ms: int | None
    p95_ms: int | None
    cost_usd: str
    tokens_in: int
    tokens_out: int


class MetricPerformance(BaseModel):
    cases_measured: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    cost_total_usd: str | None
    cost_per_complaint_usd: str | None
    llm_calls: int
    stages: list[MetricStage]


class MetricTeam(BaseModel):
    team: Literal["approval", "fraud", "auto"]
    cases: int
    open: int
    p1_open: int
    ack_overdue: int
    refund_total_myr: str
    flagged: int


class MetricsOut(BaseModel):
    role: Literal["manager", "officer", "fraud"]
    run_id: str
    sim_now: datetime
    filters: MetricFilters
    options: MetricOptions
    volume: MetricVolume
    outcomes: MetricOutcomes
    money: MetricMoney | None
    operations: MetricOperations
    guardrails: MetricGuardrails
    fraud: MetricFraud | None
    performance: MetricPerformance
    teams: list[MetricTeam] | None
    unavailable: dict[str, str]


# --- Endpoint (API builder implements) --------------------------------------------------------------------------------


@router.get("/metrics")
def get_metrics(
    user: User,
    run_id: str = db.LIVE,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    channel: str | None = None,
) -> MetricsOut:
    from teratai.ops import metrics  # deferred: ops.metrics imports the models above

    auth.require_run(user, run_id)
    if category is not None and category not in get_args(Category):
        raise HTTPException(422, detail=f"unknown category {category!r}")
    if channel is not None and channel not in get_args(Channel):
        raise HTTPException(422, detail=f"unknown channel {channel!r}")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail="date_from must not be after date_to")
    clause, params = auth.case_scope(user)
    with db.connect() as con:
        case_rows = con.execute(f"SELECT c.* FROM cases c WHERE c.run_id=? AND ({clause})", (run_id, *params)).fetchall()
        event_rows = con.execute(
            "SELECT e.* FROM case_events e JOIN cases c ON c.run_id=e.run_id AND c.complaint_id=e.complaint_id "
            f"WHERE c.run_id=? AND ({clause})", (run_id, *params),
        ).fetchall()
    cases = [
        metrics.CaseRecord(
            complaint_id=r["complaint_id"], status=r["status"],
            received_at=datetime.fromisoformat(json.loads(r["row"])["received_at"]),
            channel=json.loads(r["row"])["channel"],
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None,
            case_state=r["case_state"], sent=bool(r["sent"]),
            human_action=json.loads(r["human_action"]) if r["human_action"] else None,
            decision=json.loads(r["agent_decision"]) if r["status"] == "done" and r["agent_decision"] else None,
        )
        for r in case_rows
    ]
    events = [
        metrics.EventRecord(
            complaint_id=e["complaint_id"], actor=e["actor"], stage=e["stage"], model=e["model"],
            tokens_in=e["tokens_in"] or 0, tokens_out=e["tokens_out"] or 0,
            cost_usd=Decimal(e["cost_usd"] or "0"), latency_ms=e["latency_ms"] or 0, action=e["action"],
        )
        for e in event_rows
    ]
    filters = MetricFilters(date_from=date_from, date_to=date_to, category=category, channel=channel)
    return metrics.compute(user.role, run_id, cases, events, settings.sim_now(), filters)
