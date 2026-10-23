"""Case trail: from whom to whom, oldest first, built from the core CaseDetail plus the ops events."""

from typing import Any

from teratai.ops import auth, cases, db


def _ts(v: Any) -> str:
    return str(v).replace("T", " ")[:19]


def _step(ts: str, frm: str, to: str, action: str, note: str, rank: int = 0) -> dict[str, Any]:
    return {"ts": ts, "from": frm, "to": to, "action": action, "note": note, "_rank": rank}


def build(detail: dict[str, Any]) -> list[dict[str, Any]]:
    case = detail["case"]
    cid = case["complaint_id"]
    steps = [_step(_ts(case["received_at"]), "Customer", "Agent", "Complaint received", case["channel"])]
    queue = cases.ROUTE_QUEUE.get(case.get("route") or "")
    agent_ts = [e["ts"] for e in detail.get("events", []) if e["actor"] == "agent"]  # not the later human actions
    decided_at = _ts(agent_ts[-1]) if agent_ts else steps[0]["ts"]
    dec = detail.get("decision")
    if dec and case["status"] == "done":
        refund = case["refund_amount_myr"]
        outcome = dec["outcome"].replace("_", " ").capitalize()
        what = f"{outcome} {cases.money(refund)}" if dec["outcome"] == "REFUND" else outcome
        target = queue or "Customer"
        note = dec.get("rule_text") or ""
        if not queue:
            note = "Sent automatically: " + note
        steps.append(_step(decided_at, "Agent", target, f"Decided: {what}, {case['priority']}", note))
    # The queue a case waited in is where assignments and escalations start from.
    waiting_in = queue
    with db.connect() as con:
        evs = con.execute("SELECT * FROM events WHERE complaint_id=? ORDER BY id", (cid,)).fetchall()
    ops_steps: list[dict[str, Any]] = []
    for e in evs:
        a, who = e["action"], e["actor"]
        if a == "assign":
            label = cases.ROLE_LABEL.get(_role_of(e["to_value"]), "Officer")
            ops_steps.append(_step(e["ts"], waiting_in or "Agent", e["to_value"], "Assigned", f"{label}, least loaded"))
        elif a == "escalate":
            lim = cases.money(_limit_of(who)) if _limit_of(who) else ""
            note = f"Over {who}'s {lim} limit. " if lim else ""
            ops_steps.append(_step(e["ts"], who, (cases.get_ops(cid) or {}).get("assigned_to") or "asyraf", "Escalated", f"{note}Reason: {e['reason']}".strip()))
        elif a == "fraud_ack":
            ops_steps.append(_step(e["ts"], who, "Fraud investigation", "Acknowledged", ""))
        elif a == "fraud_log":
            ops_steps.append(_step(e["ts"], who, "Fraud investigation", "Investigation logged", e["reason"] or ""))
        elif a == "fraud_outcome":
            ops_steps.append(_step(e["ts"], who, "Fraud investigation", f"Outcome: {e['to_value']}", e["reason"] or ""))
    h = detail.get("human_action")
    if h:
        done = h["action"] != "reject"
        reason = f"Reason: {h['reason']}" if h.get("reason") else ""
        ops_steps.append(_step(
            _ts(h["at"]), h["actor"], "Customer" if done else "Closed",
            "Approved and sent" if done else "Rejected", reason if done else f"Nothing sent. {reason}".strip(), rank=1,
        ))
    ops_steps.sort(key=lambda s: (s["ts"], s["_rank"]))
    return [{k: v for k, v in s.items() if k != "_rank"} for s in steps + ops_steps]


def _role_of(username: str) -> str:
    u = auth.get_user(username)
    return u.role if u else ""


def _limit_of(username: str) -> Any:
    u = auth.get_user(username)
    return auth.limit(u) if u else None
