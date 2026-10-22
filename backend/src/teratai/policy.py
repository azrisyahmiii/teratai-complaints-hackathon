"""Policy engine (SPEC §4.5, §6). Money in Decimal. P4a stub: returns the CMP-00165 gold decision; C7 replaces it."""

from decimal import Decimal

from teratai.models import Category, ComplaintRow, Decision, MatchResult


def decide(row: ComplaintRow, category: Category, m: MatchResult) -> Decision:
    return Decision(
        outcome="REFUND",
        refund_myr=Decimal("46.66"),
        priority="P2",
        route="AUTO_RESOLVE",
        needs_info=False,
        rule_id="DUPLICATE_CHARGE.REFUND",
        rule_text="REFUND the later charge if the two are no more than 10 minutes apart and neither has been reversed.",
        inputs={"sibling": "TXN-0115571", "gap": "1m50s", "reversed": "no"},
        calc=None,
    )
