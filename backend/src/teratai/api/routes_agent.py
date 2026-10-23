"""The fixed HTTP API every team exposes (docs/api.md): /complaints, /cases/{id}, /cases/{id}/actions, /health."""

import json
import sqlite3
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from teratai import check, db
from teratai.api import intake, states, worker
from teratai.models import FactSheet

router = APIRouter()
LIVE = db.LIVE


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.post("/complaints", status_code=202)
def post_complaint(body: intake.ComplaintIn) -> JSONResponse:
    intake.require_fields(body)
    cid = body.complaint_id.strip()
    existing = db.get_case(LIVE, cid)
    if existing is not None:
        return JSONResponse({"complaint_id": cid, "status": existing["status"]}, status_code=200)
    row, channel_known = intake.build_row(body)
    if not db.insert_processing(LIVE, cid, row.model_dump_json()):
        again = db.get_case(LIVE, cid)
        return JSONResponse({"complaint_id": cid, "status": again["status"] if again else "processing"}, 200)
    worker.submit(row, channel_known)
    return JSONResponse({"complaint_id": cid, "status": "processing"}, status_code=202)


def money(v: str) -> str:
    return str(Decimal(v).quantize(Decimal("0.01")))


def case_view(r: sqlite3.Row) -> dict[str, Any]:
    out: dict[str, Any] = {"complaint_id": r["complaint_id"], "status": r["status"]}
    if r["status"] == "error":
        out["error"] = r["error"] or "unknown error"
    if r["status"] != "done":
        return out
    ad = json.loads(r["agent_decision"])
    out.update(
        category=ad["category"],
        matched_txn_id=ad["matched_txn_id"],
        outcome=ad["outcome"],
        refund_amount_myr=money(ad["refund_amount_myr"]),
        priority=ad["priority"],
        reply_language=ad["reply_language"],
        route=ad["route"],
        reply_text=ad["reply_text"],
        self_check="passed" if ad["check_ok"] else "flagged",
        case_state=r["case_state"],
        sent=bool(r["sent"]),
        human_action=json.loads(r["human_action"]) if r["human_action"] else None,
    )
    return out


@router.get("/cases/{complaint_id}")
def get_case(complaint_id: str) -> dict[str, Any]:
    r = db.get_case(LIVE, complaint_id)
    if r is None:
        raise HTTPException(404, detail=f"case {complaint_id} not found")
    return case_view(r)


class ActionIn(BaseModel):
    action: Literal["approve", "reject", "edit_approve"]
    actor: str = ""
    reason: str = ""
    reply_text: str | None = None


@router.post("/cases/{complaint_id}/actions")
def post_action(complaint_id: str, body: ActionIn) -> dict[str, Any]:
    r = db.get_case(LIVE, complaint_id)
    if r is None:
        raise HTTPException(404, detail=f"case {complaint_id} not found")
    if not body.actor.strip():
        raise HTTPException(422, detail="actor is required")
    if body.action in ("reject", "edit_approve") and not body.reason.strip():
        raise HTTPException(422, detail=f"reason is required for {body.action}")
    if body.action == "edit_approve" and not (body.reply_text or "").strip():
        raise HTTPException(422, detail="reply_text is required for edit_approve")
    if r["status"] != "done" or r["case_state"] != states.AWAITING:
        raise HTTPException(409, detail=f"case is not awaiting approval (state: {r['case_state'] or r['status']})")
    ad = json.loads(r["agent_decision"])
    sent_text: str | None
    if body.action == "approve":
        sent_text = ad["reply_text"]
    elif body.action == "edit_approve":
        sent_text = body.reply_text
        res = check.check_reply(sent_text or "", FactSheet.model_validate(ad["facts"]))
        if not res.ok:
            raise HTTPException(422, detail=["edited reply failed the self-check", *[i.message for i in res.issues]])
    else:
        sent_text = None
    state, sent = states.after_action(body.action)
    at = db.now()
    actor = body.actor.strip()
    human = {"action": body.action, "actor": actor, "reason": body.reason, "at": at, "reply_text": sent_text}
    with db.connect() as con:
        cur = con.execute(
            "UPDATE cases SET case_state=?, sent=?, human_action=?, updated_at=? "
            "WHERE run_id=? AND complaint_id=? AND case_state=?",
            (state, int(sent), json.dumps(human), at, LIVE, complaint_id, states.AWAITING),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail="case is no longer awaiting approval")
        if sent and sent_text is not None:
            con.execute(
                "INSERT INTO outbox(run_id, complaint_id, ts, language, text, authorised_by) VALUES(?,?,?,?,?,?)",
                (LIVE, complaint_id, at, ad["reply_language"], sent_text, actor),
            )
    db.add_event(LIVE, complaint_id, actor, body.action, None, {"reason": body.reason, "sent": sent})
    updated = db.get_case(LIVE, complaint_id)
    assert updated is not None
    return case_view(updated)
