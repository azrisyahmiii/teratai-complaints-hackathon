"""Ops service routes (docs/dev/tasks/ops-platform.md): core passthrough, auth, queues, approval, fraud, audit, trail."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from teratai.ops import auth, cases, core, db, settings, trail

router = APIRouter()
officer_or_manager = auth.require_role("officer", "manager")
fraud_or_manager = auth.require_role("fraud", "manager")
manager_only = auth.require_role("manager")
officer_only = auth.require_role("officer")


# --- passed through to the core -------------------------------------------------------------------
async def forward(request: Request, path: str) -> Response:
    r = await run_in_threadpool(
        core.send, request.method, path, params=dict(request.query_params), content=await request.body(),
        headers={"content-type": request.headers.get("content-type", "application/json")},
    )
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


@router.get("/api/cases")
async def pass_cases(request: Request) -> Response:
    return await forward(request, "/api/cases")


@router.get("/api/cases/{complaint_id}")
async def pass_case_detail(request: Request, complaint_id: str) -> Response:
    return await forward(request, f"/api/cases/{complaint_id}")


@router.post("/api/cases/{complaint_id}/check-reply")
async def pass_check_reply(request: Request, complaint_id: str) -> Response:
    return await forward(request, f"/api/cases/{complaint_id}/check-reply")


@router.get("/api/outbox")
async def pass_outbox(request: Request) -> Response:
    return await forward(request, "/api/outbox")


@router.post("/complaints")
async def pass_complaint(request: Request) -> Response:
    return await forward(request, "/complaints")


@router.get("/cases/{complaint_id}")
async def pass_agent_case(request: Request, complaint_id: str) -> Response:
    return await forward(request, f"/cases/{complaint_id}")


@router.post("/cases/{complaint_id}/actions")
async def pass_actions(request: Request, complaint_id: str) -> Response:
    return await forward(request, f"/cases/{complaint_id}/actions")


@router.get("/health")
def health() -> dict[str, bool]:
    try:
        ok = core.send("GET", "/health").status_code == 200
    except HTTPException:
        ok = False
    return {"ok": True, "core": ok}


# --- auth -----------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def login(body: LoginIn, response: Response) -> dict[str, object]:
    user = auth.authenticate(body.username.strip(), body.password)
    if user is None:
        raise HTTPException(401, detail="Wrong username or password")
    response.set_cookie(
        settings.COOKIE, auth.make_cookie(user.username), httponly=True, samesite="lax",
        max_age=settings.SESSION_SECONDS,
    )
    db.add_event(None, user.username, user.role, "login", None, None, None)
    return auth.me(user)


@router.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(settings.COOKIE)
    return {"ok": True}


@router.get("/api/me")
def get_me(user: Annotated[auth.User, Depends(auth.current_user)]) -> dict[str, object]:
    return auth.me(user)


# --- queues and case view -------------------------------------------------------------------------
@router.get("/api/ops/queue")
def get_queue(user: Annotated[auth.User, Depends(auth.current_user)]) -> dict[str, Any]:
    return cases.queue(user)


@router.get("/api/ops/escalations")
def escalations(user: Annotated[auth.User, Depends(manager_only)]) -> dict[str, Any]:
    items = [c for c in cases.queue(user)["items"] if c["ops_state"] == "escalated"]
    return {"items": items}


def must_find(complaint_id: str, user: auth.User) -> dict[str, Any]:
    c = cases.find(complaint_id, user)
    if c is None:
        raise HTTPException(404, detail=f"case {complaint_id} not found")
    return c


@router.get("/api/ops/cases/{complaint_id}")
def case_view(complaint_id: str, user: Annotated[auth.User, Depends(auth.current_user)]) -> dict[str, Any]:
    c = must_find(complaint_id, user)
    detail = core.call("GET", f"/api/cases/{complaint_id}")
    extra = {k: c[k] for k in ("ops_state", "assigned_to", "escalated_by", "escalation_reason", "fraud_outcome",
                               "over_my_limit")}
    return {"case": detail, "ops": extra, "trail": trail.build(detail)}


@router.get("/api/ops/cases/{complaint_id}/trail")
def get_trail(complaint_id: str, user: Annotated[auth.User, Depends(auth.current_user)]) -> dict[str, Any]:
    must_find(complaint_id, user)
    return {"items": trail.build(core.call("GET", f"/api/cases/{complaint_id}"))}


# --- officer and manager: two-tier approval -------------------------------------------------------
class ApproveIn(BaseModel):
    reason: str = ""
    reply_text: str | None = None


class ReasonIn(BaseModel):
    reason: str = ""


def need_reason(reason: str) -> str:
    if not reason.strip():
        raise HTTPException(422, detail="reason is required")
    return reason.strip()


def act(user: auth.User, c: dict[str, Any], action: str, reason: str, reply_text: str | None = None,
        actor: str | None = None) -> dict[str, Any]:
    """Send one approve / reject / edit_approve to the core as this user, then close the ops case."""
    cid = c["complaint_id"]
    body: dict[str, Any] = {"action": action, "actor": actor or user.username, "reason": reason}
    if reply_text is not None:
        body["reply_text"] = reply_text
    res = core.call("POST", f"/cases/{cid}/actions", json=body)
    new_state = res["case_state"]
    cases.set_ops(cid, ops_state="closed")
    db.add_event(cid, user.username, user.role, action, "case_state", cases.AWAITING, new_state, reason or None)
    if action == "edit_approve":
        db.add_event(cid, user.username, user.role, action, "reply_text", None, reply_text, reason or None)
    return must_find(cid, user)


def awaiting(c: dict[str, Any]) -> None:
    if c["case_state"] != cases.AWAITING:
        raise HTTPException(409, detail=f"case is not awaiting approval (state: {c['case_state']})")


@router.post("/api/ops/cases/{complaint_id}/approve")
def approve(complaint_id: str, body: ApproveIn, user: Annotated[auth.User, Depends(officer_or_manager)]) -> dict[str, Any]:
    c = must_find(complaint_id, user)
    awaiting(c)
    if c["ops_state"] == "escalated" and user.role != "manager":
        raise HTTPException(409, detail="case is escalated to a manager")
    if c["over_my_limit"] and user.limit is not None:
        raise HTTPException(
            403, detail=f"{cases.money(c['refund_amount_myr'])} is over your {cases.money(user.limit)} limit. "
            "Escalate to a manager.",
        )
    edited = body.reply_text is not None and body.reply_text.strip() != ""
    return act(user, c, "edit_approve" if edited else "approve", body.reason.strip(),
               body.reply_text if edited else None)


@router.post("/api/ops/cases/{complaint_id}/reject")
def reject(complaint_id: str, body: ReasonIn, user: Annotated[auth.User, Depends(officer_or_manager)]) -> dict[str, Any]:
    reason = need_reason(body.reason)
    c = must_find(complaint_id, user)
    awaiting(c)
    if c["ops_state"] == "escalated" and user.role != "manager":
        raise HTTPException(409, detail="case is escalated to a manager")
    return act(user, c, "reject", reason)


@router.post("/api/ops/cases/{complaint_id}/escalate")
def escalate(complaint_id: str, body: ReasonIn, user: Annotated[auth.User, Depends(officer_only)]) -> dict[str, Any]:
    reason = need_reason(body.reason)
    c = must_find(complaint_id, user)
    if c["ops_state"] == "escalated":
        raise HTTPException(409, detail="case is already escalated")
    awaiting(c)
    cases.set_ops(complaint_id, ops_state="escalated", assigned_to="manager", escalated_by=user.username,
                  escalation_reason=reason)
    db.add_event(complaint_id, user.username, user.role, "escalate", "ops_state", c["ops_state"], "escalated", reason)
    return must_find(complaint_id, user)


@router.post("/api/ops/cases/{complaint_id}/manager-approve")
def manager_approve(complaint_id: str, body: ReasonIn, user: Annotated[auth.User, Depends(manager_only)]) -> dict[str, Any]:
    reason = need_reason(body.reason)
    c = must_find(complaint_id, user)
    awaiting(c)
    res = act(user, c, "approve", reason, actor="manager")
    db.add_event(complaint_id, user.username, user.role, "manager_approve", "ops_state", c["ops_state"], "closed", reason)
    return res


@router.post("/api/ops/cases/{complaint_id}/manager-reject")
def manager_reject(complaint_id: str, body: ReasonIn, user: Annotated[auth.User, Depends(manager_only)]) -> dict[str, Any]:
    reason = need_reason(body.reason)
    c = must_find(complaint_id, user)
    awaiting(c)
    res = act(user, c, "reject", reason, actor="manager")
    db.add_event(complaint_id, user.username, user.role, "manager_reject", "ops_state", c["ops_state"], "closed", reason)
    return res


# --- fraud analyst --------------------------------------------------------------------------------
class NoteIn(BaseModel):
    note: str = ""


class OutcomeIn(BaseModel):
    outcome: Literal["confirmed_fraud", "not_fraud", "recall_succeeded", "recall_failed"]
    reason: str = ""


def fraud_case(complaint_id: str, user: auth.User) -> dict[str, Any]:
    c = must_find(complaint_id, user)
    if c["case_state"] != cases.WITH_FRAUD:
        raise HTTPException(409, detail=f"case is not with the fraud team (state: {c['case_state']})")
    if c["ops_state"] == "closed":
        raise HTTPException(409, detail="case is already closed")
    return c


def fraud_step(c: dict[str, Any], user: auth.User, action: str, ops_state: str, reason: str | None,
               logged: tuple[str, str | None, str] | None = None, **extra: Any) -> dict[str, Any]:
    """`logged` = (field, from, to) for the audit row when it is not the ops_state change itself."""
    cid = c["complaint_id"]
    cases.set_ops(cid, ops_state=ops_state, **extra)
    field, old, new = logged or ("ops_state", c["ops_state"], ops_state)
    db.add_event(cid, user.username, user.role, action, field, old, new, reason)
    return must_find(cid, user)


@router.post("/api/ops/cases/{complaint_id}/fraud-ack")
def fraud_ack(complaint_id: str, user: Annotated[auth.User, Depends(fraud_or_manager)]) -> dict[str, Any]:
    c = fraud_case(complaint_id, user)
    return fraud_step(c, user, "fraud_ack", "acknowledged", None, assigned_to=user.username)


@router.post("/api/ops/cases/{complaint_id}/fraud-log")
def fraud_log(complaint_id: str, body: NoteIn, user: Annotated[auth.User, Depends(fraud_or_manager)]) -> dict[str, Any]:
    if not body.note.strip():
        raise HTTPException(422, detail="note is required")
    c = fraud_case(complaint_id, user)
    return fraud_step(c, user, "fraud_log", "investigating", body.note.strip())


@router.post("/api/ops/cases/{complaint_id}/fraud-outcome")
def fraud_outcome(complaint_id: str, body: OutcomeIn, user: Annotated[auth.User, Depends(fraud_or_manager)]) -> dict[str, Any]:
    c = fraud_case(complaint_id, user)
    return fraud_step(c, user, "fraud_outcome", "closed", body.reason.strip() or None,
                      logged=("fraud_outcome", None, body.outcome), fraud_outcome=body.outcome)


# --- audit ----------------------------------------------------------------------------------------
@router.get("/api/audit")
def audit(complaint_id: str | None = None, actor: str | None = None, limit: int = 200,
          *, user: Annotated[auth.User, Depends(auth.current_user)]) -> dict[str, Any]:
    cases.refresh()  # so every case seen so far has its agent_decided row
    sql, args = "SELECT * FROM events WHERE 1=1", []
    if complaint_id:
        sql += " AND complaint_id=?"
        args.append(complaint_id)
    if actor:
        sql += " AND actor=?"
        args.append(actor)
    with db.connect() as con:
        rows = con.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 1000)))).fetchall()
    return {"items": [
        {"ts": r["ts"], "complaint_id": r["complaint_id"], "actor": r["actor"], "role": r["role"],
         "action": r["action"], "field": r["field"], "from": r["from_value"], "to": r["to_value"],
         "reason": r["reason"]}
        for r in rows
    ]}

