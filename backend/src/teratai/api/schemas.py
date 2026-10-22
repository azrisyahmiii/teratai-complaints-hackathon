"""API shapes (contracts §3). After changing this file, regenerate the TS types and commit web/lib/api/*."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from teratai.models import (
    AgentDecision,
    Category,
    CheckIssue,
    ComplaintRow,
    Lang,
    Priority,
    Route,
)

CaseStatus = Literal[
    "pending", "escalated", "approved", "rejected", "sent", "investigating", "closed", "needs_info"
]
ReasonCode = Literal["WRONG_TXN", "GOODWILL", "POLICY_EXCEPTION", "CUSTOMER_PROVIDED_INFO", "OTHER"]


class CaseCreated(BaseModel):
    case_id: int
    complaint_id: str
    existing: bool


class CaseSummary(BaseModel):
    id: int
    complaint_id: str
    run_id: str
    customer_id: str
    category: Category | None
    priority: Priority | None
    route: Route | None
    status: CaseStatus
    refund_amount_myr: Decimal | None
    reply_language: Lang | None
    assigned_to: str | None
    ack_due: datetime | None
    resolve_due: datetime | None
    flags: list[str]


class CaseEvent(BaseModel):
    """One case_events row (SPEC §10): agent stage or human action."""

    id: int
    case_id: int
    ts: datetime
    actor: str
    action: str
    stage: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = {}
    tool_name: str | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    ok: bool = True


class CaseDetail(CaseSummary):
    row: ComplaintRow
    agent_decision: AgentDecision | None
    final_action: dict[str, Any] | None
    check_ok: bool | None
    check_issues: list[CheckIssue]
    events: list[CaseEvent]


class ReplyIn(BaseModel):
    text: str


class ReplyCheckOut(BaseModel):
    check_ok: bool
    issues: list[CheckIssue]
    send_enabled: bool


class ActionIn(BaseModel):
    reason_code: ReasonCode | None = None
    note: str = ""
