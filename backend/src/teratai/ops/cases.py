"""Ops view of the core's cases: first-seen bookkeeping, assignment, queues. Core data is read, never written."""

import sqlite3
import threading
from decimal import Decimal
from typing import Any

from teratai import db as platform_db
from teratai.api import routes_ui
from teratai.ops import auth, db, settings

AWAITING = "awaiting_approval"
WITH_FRAUD = "with_fraud_team"
PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}
QUEUE_ROLE = {AWAITING: "officer", WITH_FRAUD: "fraud"}
ROUTE_QUEUE = {"HUMAN_APPROVAL": "Approval queue", "FRAUD_TEAM": "Fraud queue"}
ROLE_LABEL = {"officer": "Officer", "fraud": "Fraud analyst", "manager": "Manager"}

_lock = threading.Lock()


def money(d: Decimal | str) -> str:
    """RM4,687.10"""
    return f"RM{Decimal(d):,.2f}"


def _assign_target(con: sqlite3.Connection, role: str) -> str | None:
    """Least loaded on-shift platform user; ties sort by username."""
    with platform_db.connect() as staff:
        users = staff.execute("SELECT username FROM users WHERE role=? ORDER BY username", (role,)).fetchall()
    shift = settings.on_shift()
    names = [str(r["username"]) for r in users if not shift or r["username"] in shift]
    loads = dict(con.execute("SELECT assigned_to, COUNT(*) FROM ops_cases WHERE ops_state!='closed' GROUP BY assigned_to"))
    return min(names, key=lambda name: (loads.get(name, 0), name)) if names else None


def refresh(user: auth.User) -> list[dict[str, Any]]:
    """Fetch the core's cases and bring the ops rows in line: new case -> ops row, agent_decided event, assignment."""
    items = routes_ui.list_cases(user).model_dump(mode="json")["items"]
    with _lock, db.connect() as con:
        for it in items:
            state = it["case_state"]
            if it["status"] != "done":
                continue
            row = con.execute("SELECT * FROM ops_cases WHERE complaint_id=?", (it["complaint_id"],)).fetchone()
            cid = it["complaint_id"]
            if row is None:
                role = QUEUE_ROLE.get(state)
                con.execute(
                    "INSERT INTO ops_cases(complaint_id, ops_state, updated_at) VALUES(?,?,?)",
                    (cid, "open" if role else "closed", db.now()),
                )
                db.add_event(cid, "agent", "agent", "agent_decided", "case_state", None, state)
                assigned_to = _assign_target(con, role) if role else None
                if assigned_to:
                    con.execute("UPDATE ops_cases SET assigned_to=? WHERE complaint_id=?", (assigned_to, cid))
                    db.add_event(cid, "agent", "agent", "assign", "assigned_to", None, assigned_to, "Least loaded")
            elif state not in QUEUE_ROLE and row["ops_state"] != "closed":
                con.execute("UPDATE ops_cases SET ops_state='closed', updated_at=? WHERE complaint_id=?",
                            (db.now(), cid))
    return items


def get_ops(complaint_id: str) -> dict[str, Any] | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM ops_cases WHERE complaint_id=?", (complaint_id,)).fetchone()
    return dict(r) if r else None


def set_ops(complaint_id: str, **fields: Any) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.connect() as con:
        con.execute(f"UPDATE ops_cases SET {sets}, updated_at=? WHERE complaint_id=?",
                    (*fields.values(), db.now(), complaint_id))


def ops_fields(complaint_id: str, user: auth.User | None, refund: str | None) -> dict[str, Any]:
    r = get_ops(complaint_id) or {}
    approval_limit = auth.limit(user) if user else None
    over = approval_limit is not None and Decimal(refund or "0") > approval_limit
    return {
        "ops_state": r.get("ops_state", "closed"),
        "assigned_to": r.get("assigned_to"),
        "escalated_by": r.get("escalated_by"),
        "escalation_reason": r.get("escalation_reason"),
        "fraud_outcome": r.get("fraud_outcome"),
        "over_my_limit": over,
    }


def ops_case(item: dict[str, Any], user: auth.User | None) -> dict[str, Any]:
    return item | ops_fields(item["complaint_id"], user, item.get("refund_amount_myr"))


def _sort_key(c: dict[str, Any]) -> tuple[int, str]:
    return PRIORITY_ORDER.get(c.get("priority") or "", 3), str(c["received_at"])


def queue(user: auth.User) -> dict[str, Any]:
    cases = sorted((ops_case(i, user) for i in refresh(user) if i["status"] == "done"), key=_sort_key)
    if user.role == "officer":
        items = [c for c in cases if c["case_state"] == AWAITING and c["ops_state"] != "escalated"]
    elif user.role == "fraud":
        items = [c for c in cases if c["case_state"] == WITH_FRAUD]
    else:
        open_ = [c for c in cases if c["ops_state"] != "closed" and c["case_state"] in QUEUE_ROLE]
        items = [c for c in open_ if c["ops_state"] == "escalated"] + [c for c in open_ if c["ops_state"] != "escalated"]
    counts = {
        "mine": sum(c["assigned_to"] == user.username for c in items),
        "unassigned": sum(c["assigned_to"] is None for c in items),
        "escalated": sum(c["ops_state"] == "escalated" for c in items),
    }
    return {"items": items, "counts": counts}


def find(complaint_id: str, user: auth.User) -> dict[str, Any] | None:
    for i in refresh(user):
        if i["complaint_id"] == complaint_id and i["status"] == "done":
            return ops_case(i, user)
    return None
