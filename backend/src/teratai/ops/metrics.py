"""Pure aggregation behind GET /api/metrics (docs/dev/tasks/leon-insights.md). No DB, no FastAPI.

Callers pass rows already limited to the viewer's scope (`auth.case_scope`); this module decides which *sections* a role
may see (`ROLE_SECTIONS`) and never computes the others. A missing measurement is `None` plus an `unavailable` reason.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from teratai import data
from teratai.api.routes_agent import money
from teratai.api.routes_metrics import (
    MetricBucket,
    MetricDuration,
    MetricFilters,
    MetricFraud,
    MetricGuardrails,
    MetricMoney,
    MetricOperations,
    MetricOptions,
    MetricOutcomes,
    MetricPerformance,
    MetricRate,
    MetricsOut,
    MetricStage,
    MetricTeam,
    MetricVolume,
)

Role = Literal["manager", "officer", "fraud"]

# Optional sections each role may see. Anything absent is returned as None and is never computed.
ROLE_SECTIONS: dict[str, frozenset[str]] = {
    "manager": frozenset({"money", "fraud", "teams"}),
    "officer": frozenset({"money"}),
    "fraud": frozenset({"fraud"}),
}

# Top-level pipeline stages (pipeline.process_complaint): their latencies are sequential and non-overlapping, so
# summing them gives the per-complaint latency. `extract` (inside understand), `investigate` (inside match) and
# `reply_draft` / `reply_redraft` (inside reply) are nested model/tool calls whose time is already in their parent.
TOP_LEVEL_STAGES = frozenset({"understand", "resolve", "match", "decide", "reply"})

# Case states that are "open" (waiting on a person). One place so Azri's escalation state is a one-line change.
OPEN_STATES = frozenset({"awaiting_approval", "with_fraud_team"})
PAID_STATES = frozenset({"auto_resolved", "approved"})
TEAM_BY_ROUTE: dict[str, Literal["approval", "fraud", "auto"]] = {
    "HUMAN_APPROVAL": "approval", "FRAUD_TEAM": "fraud", "AUTO_RESOLVE": "auto",
}

ZERO = Decimal(0)


@dataclass
class CaseRecord:
    complaint_id: str
    status: str
    received_at: datetime
    channel: str
    created_at: datetime | None = None
    case_state: str | None = None
    sent: bool = False
    human_action: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None  # parsed AgentDecision JSON; None until done

    @property
    def category(self) -> str | None:
        return self.decision["category"] if self.decision else None

    @property
    def refund(self) -> Decimal:
        return Decimal(self.decision["refund_amount_myr"]) if self.decision else ZERO


@dataclass
class EventRecord:
    complaint_id: str
    actor: str
    stage: str | None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = ZERO
    latency_ms: int = 0
    action: str | None = None


def effective_state(c: CaseRecord) -> str:
    """The single state used by every backlog / open count, so each case is counted exactly once."""
    if c.status != "done":
        return c.status
    return c.case_state or "unknown"


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None when there are no values."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def _rate(num: int, den: int) -> MetricRate:
    return MetricRate(numerator=num, denominator=den, pct=round(100 * num / den, 1) if den else None)


def _buckets(counts: Counter[str], amounts: dict[str, Decimal] | None = None) -> list[MetricBucket]:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        MetricBucket(key=k, count=n, amount_myr=money(str(amounts.get(k, ZERO))) if amounts is not None else None)
        for k, n in items
    ]


def _ack_due(c: CaseRecord) -> datetime | None:
    if not c.decision:
        return None
    return c.received_at + timedelta(hours=data.sla_policy()[c.decision["priority"]].ack_hours)


def _is_open(c: CaseRecord) -> bool:
    return effective_state(c) in OPEN_STATES


def _overdue(c: CaseRecord, now: datetime) -> bool:
    due = _ack_due(c)
    return _is_open(c) and due is not None and due < now


def _disputed(c: CaseRecord) -> Decimal:
    txn_id = c.decision["matched_txn_id"] if c.decision else ""
    return data.txn(txn_id).amount if txn_id and data.has_txn(txn_id) else ZERO


def _volume(cases: list[CaseRecord]) -> MetricVolume:
    done = [c for c in cases if c.decision]
    by_day = Counter(c.received_at.date().isoformat() for c in cases)
    return MetricVolume(
        total=len(cases),
        processing=sum(c.status == "processing" for c in cases),
        errors=sum(c.status == "error" for c in cases),
        by_day=[MetricBucket(key=k, count=by_day[k]) for k in sorted(by_day)],
        by_channel=_buckets(Counter(c.channel for c in cases)),
        by_category=_buckets(Counter(c.category or "" for c in done)),
        by_priority=_buckets(Counter(c.decision["priority"] for c in done if c.decision)),
        by_language=_buckets(Counter(c.decision["reply_language"] for c in done if c.decision)),
    )


def _outcomes(done: list[CaseRecord]) -> MetricOutcomes:
    counts: Counter[str] = Counter()
    amounts: dict[str, Decimal] = defaultdict(Decimal)
    for c in done:
        assert c.decision
        counts[c.decision["outcome"]] += 1
        amounts[c.decision["outcome"]] += c.refund
    routes = Counter(c.decision["route"] for c in done if c.decision)
    return MetricOutcomes(
        by_outcome=_buckets(counts, amounts),
        by_route=_buckets(routes),
        auto_resolve_rate=_rate(routes["AUTO_RESOLVE"], len(done)),
    )


def _money(done: list[CaseRecord]) -> MetricMoney:
    paid = [c for c in done if c.decision and c.decision["outcome"] == "REFUND"
            and c.sent and effective_state(c) in PAID_STATES]
    waiting = [c for c in done if c.decision and c.decision["outcome"] == "REFUND"
               and effective_state(c) == "awaiting_approval"]
    paid_total = sum((c.refund for c in paid), ZERO)
    by_cat: dict[str, Decimal] = defaultdict(Decimal)
    counts: Counter[str] = Counter()
    for c in paid + waiting:
        counts[c.category or ""] += 1
        by_cat[c.category or ""] += c.refund
    return MetricMoney(
        refunds_paid_myr=money(str(paid_total)),
        refunds_paid_count=len(paid),
        avg_refund_myr=money(str(paid_total / len(paid))) if paid else None,
        awaiting_approval_myr=money(str(sum((c.refund for c in waiting), ZERO))),
        awaiting_approval_count=len(waiting),
        refunds_by_category=_buckets(counts, by_cat),
    )


def _operations(cases: list[CaseRecord], now: datetime) -> MetricOperations:
    acted = [c for c in cases if c.human_action]
    minutes = [
        (at - c.created_at).total_seconds() / 60
        for c in acted
        if c.created_at and (at := _parse_time((c.human_action or {}).get("at"))) is not None
    ]
    return MetricOperations(
        backlog=_buckets(Counter(effective_state(c) for c in cases)),
        ack_overdue=sum(_overdue(c, now) for c in cases),
        ack_due_2h=sum(
            _is_open(c) and (due := _ack_due(c)) is not None and now <= due <= now + timedelta(hours=2) for c in cases
        ),
        turnaround=MetricDuration(
            count=len(minutes),
            p50_minutes=_round1(percentile(minutes, 50)),
            p95_minutes=_round1(percentile(minutes, 95)),
        ),
        human_actions=len(acted),
    )


def _guardrails(cases: list[CaseRecord]) -> MetricGuardrails:
    done = [c for c in cases if c.decision]
    acted = [c for c in cases if c.human_action]
    actions = [(c.human_action or {}).get("action") for c in acted]
    flags = [set(c.decision["flags"]) for c in done if c.decision]
    return MetricGuardrails(
        self_check_flagged=_rate(sum(not c.decision["check_ok"] for c in done if c.decision), len(done)),
        reply_source=_buckets(Counter(c.decision["reply"]["source"] for c in done if c.decision)),
        overrides=_rate(sum(a in ("edit_approve", "reject") for a in actions), len(acted)),
        rejections=_rate(sum(a == "reject" for a in actions), len(acted)),
        escalations=None,
        injection_suspected=sum("injection_suspected" in f for f in flags),
        degraded=sum("degraded" in f for f in flags),
        needs_info=sum("needs_info" in f for f in flags),
        vulnerable=sum("vulnerable" in f for f in flags),
    )


def _fraud(done: list[CaseRecord], now: datetime) -> MetricFraud:
    mine = [c for c in done if c.decision and c.decision["route"] == "FRAUD_TEAM"]
    open_ = [c for c in mine if _is_open(c)]
    return MetricFraud(
        total=len(mine),
        open=len(open_),
        p1_open=sum(bool(c.decision and c.decision["priority"] == "P1") for c in open_),
        ack_overdue=sum(_overdue(c, now) for c in mine),
        amount_disputed_myr=money(str(sum((_disputed(c) for c in open_), ZERO))),
        by_category=_buckets(Counter(c.category or "" for c in mine)),
        acknowledged=None, recall_attempts=None, outcomes=None,
    )


def _teams(done: list[CaseRecord], now: datetime) -> list[MetricTeam]:
    out: list[MetricTeam] = []
    for route, team in TEAM_BY_ROUTE.items():
        mine = [c for c in done if c.decision and c.decision["route"] == route]
        open_ = [c for c in mine if _is_open(c)]
        out.append(MetricTeam(
            team=team, cases=len(mine), open=len(open_),
            p1_open=sum(bool(c.decision and c.decision["priority"] == "P1") for c in open_),
            ack_overdue=sum(_overdue(c, now) for c in mine),
            refund_total_myr=money(str(sum((c.refund for c in mine), ZERO))),
            flagged=sum(not (c.decision or {}).get("check_ok", True) for c in mine),
        ))
    return out


def _performance(cases: list[CaseRecord], events: list[EventRecord]) -> MetricPerformance:
    ids = {c.complaint_id for c in cases}
    agent = [e for e in events if e.actor == "agent" and e.complaint_id in ids]
    per_case: dict[str, int] = defaultdict(int)
    for e in agent:
        if e.stage in TOP_LEVEL_STAGES:
            per_case[e.complaint_id] += e.latency_ms
    measured = {e.complaint_id for e in agent}
    total_cost = sum((e.cost_usd for e in agent), ZERO)
    by_stage: dict[str, list[EventRecord]] = defaultdict(list)
    for e in agent:
        by_stage[e.stage or ""].append(e)
    stages = [
        MetricStage(
            stage=s, count=len(es),
            p50_ms=_int(percentile([float(e.latency_ms) for e in es], 50)),
            p95_ms=_int(percentile([float(e.latency_ms) for e in es], 95)),
            cost_usd=_usd(sum((e.cost_usd for e in es), ZERO)),
            tokens_in=sum(e.tokens_in for e in es), tokens_out=sum(e.tokens_out for e in es),
        )
        for s, es in sorted(by_stage.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    lat = [float(v) for v in per_case.values()]
    return MetricPerformance(
        cases_measured=len(measured),
        latency_p50_ms=_int(percentile(lat, 50)),
        latency_p95_ms=_int(percentile(lat, 95)),
        cost_total_usd=_usd(total_cost) if measured else None,
        cost_per_complaint_usd=_usd(total_cost / len(measured)) if measured else None,
        llm_calls=sum(e.model is not None for e in agent),
        stages=stages,
    )


def _usd(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.0001")))


def _int(v: float | None) -> int | None:
    return None if v is None else round(v)


def _round1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _parse_time(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _in_filters(c: CaseRecord, f: MetricFilters) -> bool:
    day = c.received_at.date()
    return (
        (f.date_from is None or day >= f.date_from)
        and (f.date_to is None or day <= f.date_to)
        and (f.channel is None or c.channel == f.channel)
        and (f.category is None or c.category == f.category)
    )


def _dates(cases: Iterable[CaseRecord]) -> list[date]:
    return sorted(c.received_at.date() for c in cases)


def compute(
    role: Role, run_id: str, cases: list[CaseRecord], events: list[EventRecord], sim_now: datetime,
    filters: MetricFilters,
) -> MetricsOut:
    sections = ROLE_SECTIONS[role]
    days = _dates(cases)
    options = MetricOptions(
        categories=sorted({c.category for c in cases if c.category}),
        channels=sorted({c.channel for c in cases}),
        date_min=days[0] if days else None,
        date_max=days[-1] if days else None,
    )
    scoped = [c for c in cases if _in_filters(c, filters)]
    done = [c for c in scoped if c.decision]
    perf = _performance(scoped, events)
    # Workflow measurements with no stored events yet (leon-insights.md §5); switch over here when they land.
    unavailable = {
        "guardrails.escalations": "awaiting escalation workflow events",
        "operations.resolve_adherence": "awaiting the business-day SLA helper",
    }
    if "fraud" in sections:
        for name in ("acknowledged", "recall_attempts", "outcomes"):
            unavailable[f"fraud.{name}"] = "awaiting fraud workflow events"
    if perf.cases_measured == 0:
        unavailable["performance"] = "no agent events recorded for this run (batch runs store none)"
    return MetricsOut(
        role=role, run_id=run_id, sim_now=sim_now, filters=filters, options=options,
        volume=_volume(scoped),
        outcomes=_outcomes(done),
        money=_money(done) if "money" in sections else None,
        operations=_operations(scoped, sim_now),
        guardrails=_guardrails(scoped),
        fraud=_fraud(done, sim_now) if "fraud" in sections else None,
        performance=perf,
        teams=_teams(done, sim_now) if "teams" in sections else None,
        unavailable=unavailable,
    )

