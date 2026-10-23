"""Expiring, revocable staff sessions and one SQLite row-access policy for the platform."""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from decimal import Decimal
from typing import Annotated, Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from teratai import db
from teratai.ops import db as ops_db

router = APIRouter(prefix="/api")
COOKIE = "teratai_session"
SESSION_SECONDS = 8 * 60 * 60
ROLES = {"manager": "Manager", "officer": "Complaints officer", "fraud": "Fraud analyst"}


class StaffUser(BaseModel):
    username: str
    role: Literal["manager", "officer", "fraud"]
    role_label: str
    approval_limit_myr: str | None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)


def seed_users() -> None:
    """Only create missing demo users; never reset an existing password on restart."""
    with db.connect() as con:
        for username, role in (
            ("asyraf", "manager"), ("leon", "officer"), ("azri", "fraud"),
            ("vincent", "officer"), ("nishan", "fraud"),
        ):
            if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                continue
            hashed = bcrypt.hashpw(b"000000", bcrypt.gensalt()).decode()
            con.execute(
                "INSERT OR IGNORE INTO users(username, pw_hash, role, approval_limit_myr, status) VALUES(?,?,?,?,?)",
                (username, hashed, role, None if role == "manager" else "2000.00", "online"),
            )


def _user(row: sqlite3.Row) -> StaffUser:
    return StaffUser(
        username=row["username"], role=row["role"], role_label=ROLES[row["role"]],
        approval_limit_myr=row["approval_limit_myr"],
    )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request) -> StaffUser:
    token = request.cookies.get(COOKIE)
    if token:
        with db.connect() as con:
            row = con.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>?",
                (_digest(token), int(time.time())),
            ).fetchone()
        if row and row["role"] in ROLES:
            return _user(row)
    raise HTTPException(401, detail="Sign in to continue.")


User = Annotated[StaffUser, Depends(current_user)]


def require_csrf(request: Request) -> None:
    # Cross-origin forms cannot send this header; the API intentionally enables no CORS.
    if request.headers.get("X-Requested-With") != "teratai":
        raise HTTPException(403, detail="A same-origin staff request is required.")


def mutation_user(user: User, _: Annotated[None, Depends(require_csrf)]) -> StaffUser:
    return user


MutationUser = Annotated[StaffUser, Depends(mutation_user)]


def require_manager(user: User) -> StaffUser:
    if user.role != "manager":
        raise HTTPException(403, detail="Only the manager can export all agent decisions.")
    return user


Manager = Annotated[StaffUser, Depends(require_manager)]


def require_run(user: StaffUser, run_id: str) -> None:
    if run_id != db.LIVE and user.role != "manager":
        raise HTTPException(403, detail="Only the manager can access evaluation runs.")


def case_scope(user: StaffUser) -> tuple[str, tuple[str, ...]]:
    """SQL predicate for the `c` case alias; never use mutable state as the team boundary."""
    if user.role == "manager":
        return "1=1", ()
    routes = "('FRAUD_TEAM')" if user.role == "fraud" else "('HUMAN_APPROVAL','AUTO_RESOLVE')"
    return (
        (f"(json_extract(c.agent_decision, '$.route') IN {routes} "
         "OR (c.status!='done' AND c.submitted_by=?))"),
        (user.username,),
    )


def require_case(user: StaffUser, run_id: str, cid: str) -> sqlite3.Row:
    require_run(user, run_id)
    row = db.get_case(run_id, cid)
    if row is None:
        raise HTTPException(404, detail=f"case {cid} not found")
    clause, params = case_scope(user)
    with db.connect() as con:
        allowed = con.execute(
            f"SELECT 1 FROM cases c WHERE c.run_id=? AND c.complaint_id=? AND ({clause})",
            (run_id, cid, *params),
        ).fetchone()
    if allowed is None:
        raise HTTPException(403, detail="This case belongs to another team.")
    return row


def action_block_reason(user: StaffUser, row: sqlite3.Row) -> str | None:
    if user.role == "fraud":
        return "Fraud analysts cannot approve general complaints."
    if user.role == "officer" and row["agent_decision"]:
        decision = json.loads(row["agent_decision"])
        if "sensitive" in json.loads(row["flags"] or "[]"):
            return "A sensitive case requires manager approval."
        if Decimal(decision["refund_amount_myr"]) > Decimal(user.approval_limit_myr or "0"):
            return "This refund is above your approval limit and requires the manager."
        with ops_db.connect() as con:
            escalated = con.execute(
                "SELECT 1 FROM ops_cases WHERE complaint_id=? AND ops_state='escalated'",
                (row["complaint_id"],),
            ).fetchone()
        if escalated:
            return "This case is escalated and requires manager approval."
    return None


@router.get("/me")
def me(user: User) -> StaffUser:
    return user


@router.post("/auth/login", dependencies=[Depends(require_csrf)])
def login(body: LoginIn, request: Request, response: Response) -> StaffUser:
    username = body.username.strip().lower()
    source = request.client.host if request.client else "unknown"
    now = int(time.time())
    with db.connect() as con:
        con.execute("DELETE FROM login_attempts WHERE at<?", (now - 300,))
        con.execute("BEGIN IMMEDIATE")
        tries = con.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE username=? AND source=?", (username, source)
        ).fetchone()[0]
        if tries >= 10:
            con.rollback()
            raise HTTPException(429, detail="Too many sign-in attempts. Try again in five minutes.")
        con.execute("INSERT INTO login_attempts(username, source, at) VALUES(?,?,?)", (username, source, now))
        con.commit()
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        # Always perform the hash check, including for an unknown ID, to keep the failure response consistent.
        fallback = con.execute("SELECT pw_hash FROM users WHERE username='asyraf'").fetchone()[0]
        password = body.password.encode()
        valid = len(password) <= 72 and bcrypt.checkpw(password, (row["pw_hash"] if row else fallback).encode())
        if not valid or row is None or row["role"] not in ROLES:
            raise HTTPException(401, detail="Incorrect staff ID or password.")
        old = request.cookies.get(COOKIE)
        if old:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(old),))
        con.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        con.execute("DELETE FROM login_attempts WHERE username=? AND source=?", (username, source))
        token = secrets.token_urlsafe(32)
        con.execute("INSERT INTO sessions VALUES(?,?,?)", (_digest(token), row["id"], now + SESSION_SECONDS))
    ops_db.add_event(None, username, row["role"], "login", None, None, None)
    response.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", path="/",
        secure=os.environ.get("AUTH_COOKIE_SECURE") == "1" or request.url.scheme == "https",
    )
    return _user(row)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
