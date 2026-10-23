"""Read-only, role-scoped insights over stored cases and agent events (docs/dev/tasks/leon-insights.md)."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from teratai import db
from teratai.api.auth import User

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
    raise HTTPException(501, detail="metrics not implemented yet")
