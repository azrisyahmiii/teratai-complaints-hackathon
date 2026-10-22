"""Decision-bound self-check (SPEC §4.7). P4a stub: flags only unknown TXN ids and RM amounts; C7 replaces it."""

import re
from decimal import Decimal

from teratai.models import CheckIssue, CheckResult, FactSheet

_TXN = re.compile(r"TXN-\d{7}")
_RM = re.compile(r"RM\s?([\d,]+(?:\.\d{1,2})?)")


def check_reply(text: str, facts: FactSheet) -> CheckResult:
    issues: list[CheckIssue] = []
    for txn in _TXN.findall(text):
        if txn not in facts.ids.values():
            issues.append(
                CheckIssue(
                    code="TXN_ID", message=f"transaction {txn} is not in this case's evidence", token=txn
                )
            )
    allowed = set(facts.amounts.values()) | {facts.refund_myr}
    for raw in _RM.findall(text):
        amount = Decimal(raw.replace(",", ""))
        if not any(abs(amount - a) <= Decimal("0.005") for a in allowed):
            token = f"RM{amount:.2f}"
            issues.append(
                CheckIssue(
                    code="AMOUNT", message=f"amount {token} is not in this case's evidence", token=token
                )
            )
    return CheckResult(ok=not issues, issues=issues)
