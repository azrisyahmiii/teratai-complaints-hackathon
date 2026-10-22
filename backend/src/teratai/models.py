"""Stage data shared by Core and Platform (contracts §1). Change only via a joint `contracts: …` commit.

Money is `Decimal` everywhere; pydantic serialises it to a JSON string ("46.66").
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Category = Literal[
    "DUPLICATE_CHARGE",
    "FAILED_TRANSFER",
    "ATM_NOT_DISPENSED",
    "UNAUTHORISED_CARD",
    "SCAM_TRANSFER",
    "FEE_DISPUTE",
    "SERVICE_QUALITY",
]
Outcome = Literal["REFUND", "DECLINE", "INVESTIGATE", "INFO_ONLY"]
Priority = Literal["P1", "P2", "P3"]
Lang = Literal["EN", "MS"]
Route = Literal["AUTO_RESOLVE", "HUMAN_APPROVAL", "FRAUD_TEAM"]
Mode = Literal["live", "batch"]
Channel = Literal["App chat", "Email", "Call centre note", "Branch form", "Social media DM"]

CSV_COLUMNS = [
    "complaint_id",
    "category",
    "matched_txn_id",
    "outcome",
    "refund_amount_myr",
    "priority",
    "reply_language",
    "route",
    "reply_text",
]


class ComplaintRow(BaseModel):
    """One complaints.csv row."""

    complaint_id: str | None = None
    customer_id: str
    received_at: datetime
    channel: Channel
    subject: str = ""
    text: str


class Issue(BaseModel):
    """SPEC §4.2 extraction schema, one per issue."""

    category: Category
    amount: Decimal | None = None
    amount_approx: bool = False
    counterparty: str | None = None
    date_phrase: str | None = None
    card_last4: str | None = None
    fee_type: Literal["monthly_service", "debit_annual", "cc_annual"] | None = None
    fee_month: str | None = None
    card_in_possession: bool | None = None


class Understanding(BaseModel):
    issues: list[Issue]
    top3: list[tuple[Category, float]]
    source: Literal["rules", "classifier", "llm"]
    language: Lang
    language_reason: str
    is_complaint: bool
    injection_suspected: bool
    scam_cue: bool


class DateWindow(BaseModel):
    """SPEC §4.3: inclusive search window; exact_day scores higher."""

    start: date
    end: date
    exact_day: date | None = None
    phrase: str | None = None


class Candidate(BaseModel):
    txn_id: str
    score: int
    breakdown: dict[str, int]


class MatchResult(BaseModel):
    status: Literal["UNIQUE", "NONE", "AMBIGUOUS", "WRONG_CUSTOMER", "NO_TXN"]
    txn_id: str | None
    window: DateWindow
    candidates: list[Candidate]
    related: dict[str, str]  # sibling / reversal / journal ids
    source: Literal["matcher", "investigator"]


class Decision(BaseModel):
    outcome: Outcome
    refund_myr: Decimal
    priority: Priority
    route: Route
    needs_info: bool
    rule_id: str
    rule_text: str
    inputs: dict[str, str]
    calc: str | None = None  # "1500.00 − 950.00 = 550.00"


class FactSheet(BaseModel):
    customer_name: str
    honorific: str
    language: Lang
    category: Category
    outcome: Outcome
    refund_myr: Decimal
    ids: dict[str, str]
    amounts: dict[str, Decimal]
    dates: dict[str, date]
    sla_days: int


class CheckIssue(BaseModel):
    code: Literal["TXN_ID", "AMOUNT", "OUTCOME", "LANGUAGE", "HYGIENE", "PHONE_URL", "DATE"]
    message: str  # e.g. "amount RM600.00 is not in this case's evidence"
    token: str | None = None


class CheckResult(BaseModel):
    ok: bool
    issues: list[CheckIssue]


class Reply(BaseModel):
    text: str
    source: Literal["llm", "redraft", "template"]
    check: CheckResult
    drafts: list[str]


class StageEvent(BaseModel):
    """One case_events row produced by the agent."""

    stage: str
    ok: bool
    latency_ms: int
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal(0)
    tool_name: str | None = None
    payload: dict[str, Any]


class AgentDecision(BaseModel):
    """Immutable (SPEC §4.8). The predictions.csv row comes only from this.

    WRONG_CUSTOMER (§6): match.status says so, flags has "wrong_customer", reply_text "";
    the CSV row uses the §6 NEEDS_INFO defaults.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    run_id: str
    customer_id: str
    category: Category
    category_conf: float
    matched_txn_id: str  # "" when none
    outcome: Outcome
    refund_amount_myr: Decimal
    priority: Priority
    reply_language: Lang
    route: Route
    reply_text: str
    check_ok: bool
    flags: list[str]
    understanding: Understanding
    match: MatchResult
    decision: Decision
    facts: FactSheet
    reply: Reply

    def to_csv_row(self) -> dict[str, str]:
        """predictions.csv columns, refund formatted "46.66"."""
        return {
            "complaint_id": self.complaint_id,
            "category": self.category,
            "matched_txn_id": self.matched_txn_id,
            "outcome": self.outcome,
            "refund_amount_myr": str(self.refund_amount_myr.quantize(Decimal("0.01"))),
            "priority": self.priority,
            "reply_language": self.reply_language,
            "route": self.route,
            "reply_text": self.reply_text,
        }


Emit = Callable[[StageEvent], None]
