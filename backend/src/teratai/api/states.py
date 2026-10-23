"""Case state machine for the organisers' API (docs/api.md). Pure functions."""

from teratai.models import Route

AUTO_RESOLVED = "auto_resolved"
AWAITING = "awaiting_approval"
WITH_FRAUD = "with_fraud_team"
APPROVED = "approved"
REJECTED = "rejected"


def initial_state(route: Route) -> tuple[str, bool]:
    """(case_state, sent) straight after the agent decides."""
    if route == "AUTO_RESOLVE":
        return AUTO_RESOLVED, True
    if route == "HUMAN_APPROVAL":
        return AWAITING, False
    return WITH_FRAUD, True  # the holding reply goes out


def after_action(action: str) -> tuple[str, bool]:
    """(case_state, sent) after a human acts on an awaiting_approval case."""
    if action in ("approve", "edit_approve"):
        return APPROVED, True
    return REJECTED, False
